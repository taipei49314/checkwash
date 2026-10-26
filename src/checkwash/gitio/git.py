"""Git plumbing access. git is the only external binary checkwash talks to.

The head side may be attacker-controlled; nothing here executes repo content.
"""

from __future__ import annotations

import os
import re
import hashlib
import stat
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass

from checkwash.change import EngineError, FileChange, SourceOverLimit, UnreadSide
from checkwash.gitio.snapshot import GitSnapshot, TreeAlias, WorkingTreeSnapshot


class GitError(Exception):
    pass


class GitRootUnresolved(GitError):
    """Git confirmed a subdirectory of a work tree but its root could not be
    resolved (#416). A command that then keeps `--repo` as given says so;
    outside Git it stays silent."""


def _run(repo: str, args: list[str], *, env: dict[str, str] | None = None,
         timeout: float = 60, stdin=None) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
            stdin=stdin,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("git read could not complete") from exc
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args[:2])} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


@dataclass(frozen=True)
class RepositoryRoot:
    """Where a command reads the repository that `--repo` names (#416).

    `path` is Git's `--show-toplevel` when `--repo` is a subdirectory of a
    work tree, and `--repo` itself everywhere else. `prefix` is Git's
    `--show-prefix` for `--repo` (`pkg/sub/`), empty unless `path` moved.
    """

    path: str
    prefix: str = ""


def resolve_repository_root(repo: str, *, env: dict[str, str] | None = None,
                            timeout: float = 60, stdin=None) -> RepositoryRoot:
    """The directory every later Git call runs in, for `--repo` (#416).

    From a subdirectory Git answers in two path bases: `diff`, `status` and
    `cat-file <rev>:<path>` are root-relative, while `ls-tree`, `git grep`
    and the working-tree walker see only the subtree, so a run could fail or
    read the wrong blob. At the root, and where Git has no work tree (a bare
    repository, inside `.git`), `repo` comes back unchanged. The toplevel is
    a second query because `--show-toplevel` fails without a work tree. It is
    never `repo` joined with `--show-cdup`: through a symlinked or junction
    directory a lexical `..` lands elsewhere. Any failure, Git's own message
    included, is a GitError; the caller decides whether it is fatal. Once Git
    has answered that `repo` is a subdirectory of a work tree, it is a
    GitRootUnresolved, so a caller that keeps `repo` can say why. Both
    queries run with `env`, `timeout` and `stdin`; the defaults are every
    other Git call's (60 seconds, inherited stdin), and `checkwash doctor`
    passes its own (#500).
    """
    query = {"env": env, "timeout": timeout, "stdin": stdin}
    raw = _run(repo, ["rev-parse", "--is-inside-work-tree", "--show-prefix"], **query)
    answer = re.fullmatch(rb"(true|false)\n([^\n]*)\n", raw)
    if answer is None:
        # Git prints the prefix raw, so a directory name holding a newline
        # breaks the line format after Git has confirmed a work tree.
        if raw.startswith(b"true\n"):
            raise GitRootUnresolved("git rev-parse returned an invalid prefix")
        raise GitError("git rev-parse returned an invalid work-tree answer")
    if answer.group(1) != b"true" or not answer.group(2):
        return RepositoryRoot(repo)
    try:
        prefix = answer.group(2).decode("utf-8", "strict")
    except UnicodeError as exc:
        raise GitRootUnresolved("git rev-parse returned an undecodable prefix") from exc
    if not prefix.endswith("/") or any(part in {"", ".", ".."} for part in prefix[:-1].split("/")):
        raise GitRootUnresolved(f"git rev-parse returned an invalid prefix {prefix!r}")
    try:
        raw = _run(repo, ["rev-parse", "--show-toplevel"], **query)
    except GitError as exc:
        raise GitRootUnresolved(str(exc)) from exc
    try:
        top = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise GitRootUnresolved("git rev-parse returned an undecodable repository root") from exc
    if not top.endswith("\n") or "\n" in top[:-1]:
        raise GitRootUnresolved("git rev-parse returned an incomplete repository root")
    top = top[:-1]
    if not top or not os.path.isabs(top) or not os.path.isdir(top):
        raise GitRootUnresolved(f"git rev-parse returned an unusable repository root {top!r}")
    return RepositoryRoot(top, prefix)


def rev_parse(repo: str, rev: str) -> str:
    return _run(repo, ["rev-parse", "--short", rev]).decode("ascii").strip()


def merge_base(repo: str, a: str, b: str) -> str:
    return _run(repo, ["merge-base", a, b]).decode("ascii").strip()


def resolve_commit(repo: str, rev: str) -> str:
    raw = _run(repo, ["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"])
    if not re.fullmatch(b"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", raw):
        raise GitError("invalid resolved commit identity")
    return raw.decode("ascii").strip()


def read_commit_parents(repo: str, rev: str) -> list[str]:
    """Read actual object headers, including parents hidden by shallow history."""
    revision = resolve_commit(repo, rev)
    raw = _run(repo, ["cat-file", "commit", revision])
    if len(raw) > 1_000_000:
        raise GitError("commit object exceeds the input byte limit")
    algorithm = "sha1" if len(revision) == 40 else "sha256"
    actual = hashlib.new(algorithm, b"commit " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if actual != revision:
        raise GitError("commit bytes do not match their object identity")
    header, separator, _message = raw.partition(b"\n\n")
    fields = header.split(b"\n")
    oid_pattern = b"[0-9a-f]{" + str(len(revision)).encode("ascii") + b"}"
    if not separator or not re.fullmatch(b"tree " + oid_pattern, fields[0]):
        raise GitError("invalid commit object header")
    parents = []
    for field in fields[1:]:
        if field.startswith(b"parent "):
            if not re.fullmatch(b"parent " + oid_pattern, field):
                raise GitError("invalid commit parent identity")
            parents.append(field[7:].decode("ascii"))
    return parents


class GitSourceOverLimit(GitError):
    """A size refusal re-raised as a GitError; `unread` names the path, side,
    size and limit, and so does the message (#415)."""

    def __init__(self, unread: UnreadSide):
        super().__init__(unread.message())
        self.unread = unread


def _git_error(exc: EngineError) -> GitError:
    if isinstance(exc, SourceOverLimit):
        return GitSourceOverLimit(exc.unread)
    return GitError(str(exc))


def _read_blob(repo: str, rev: str, path: str, *, side: str | None = None,
               unread_oversized: bool = False, stream_prefix: bool = True) -> bytes | UnreadSide | None:
    try:
        return GitSnapshot(repo, rev, side=side).read(path, unread_oversized=unread_oversized,
                                                      stream_prefix=stream_prefix)
    except EngineError as exc:
        raise _git_error(exc) from exc


def read_base_file(repo: str, base: str, path: str, *, side: str = "base") -> bytes | None:
    """One file as `base` holds it; a file over the source byte limit raises
    `GitSourceOverLimit`. `side` is the diff side a size refusal names."""
    return _read_blob(repo, base, path, side=side)


def base_alias(repo: str, base: str, path: str) -> TreeAlias | None:
    """The entry of `base`'s tree that `path`, which the tree lacks, can
    stand for on disk, or None: `GitSnapshot.alias` (#500)."""
    try:
        return GitSnapshot(repo, base, side="base").alias(path)
    except EngineError as exc:
        raise _git_error(exc) from exc


def read_blobs(repo: str, specs: list[tuple[str, str]], *, required=False,
               sides: dict[str, str] | None = None,
               unread_oversized=False) -> dict[tuple[str, str], bytes | UnreadSide | None]:
    """Read exact inventoried OIDs in bounded batches, preserving failures.

    GitSnapshot separates tree absence (and explicit opaque gitlink entries)
    from failed blob reads. It validates process status, ordered headers,
    sizes, delimiters and content identities; no permissive fallback is used.
    `sides` names each revision's diff side for a size refusal; with
    `unread_oversized` a blob over the limit comes back as an `UnreadSide`
    (#415).
    """
    grouped: dict[str, list[str]] = {}
    for revision, path in sorted(set(specs)):
        grouped.setdefault(revision, []).append(path)
    result = {}
    try:
        for revision, paths in grouped.items():
            snapshot = GitSnapshot(repo, revision, side=(sides or {}).get(revision))
            blobs = snapshot.read_many(paths, unread_oversized=unread_oversized)
            if required and any(data is None and path not in snapshot._opaque for path, data in blobs.items()):
                raise GitError("required diff side is absent from its tree")
            result.update({(revision, path): data for path, data in blobs.items()})
    except EngineError as exc:
        raise _git_error(exc) from exc
    return result


def grep_head_paths(repo: str, rev: str, needles: list[str]) -> list[str]:
    """Whole-tree fixed-string search: only clean exit 1 means no matches."""
    if not needles:
        return []
    revision = resolve_commit(repo, rev)
    args = ["grep", "-l", "-F", "-z"]
    for needle in needles:
        args.extend(["-e", needle])
    args.append(revision)
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("head search could not complete") from exc
    if proc.returncode == 1 and not proc.stdout and not proc.stderr:
        return []
    if proc.returncode != 0 or proc.stderr:
        raise GitError("head search Git read failed")
    raw = proc.stdout
    if not raw or not raw.endswith(b"\0") or len(raw) > 32_000_000:
        raise GitError("head search returned incomplete or over-budget records")
    prefix = revision.encode("ascii") + b":"
    paths = []
    for record in raw[:-1].split(b"\0"):
        if not record.startswith(prefix) or record == prefix:
            raise GitError("head search returned invalid path record")
        try:
            path = record[len(prefix):].decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise GitError("head search returned undecodable path") from exc
        if any(c in path for c in "\r\n\0"):
            raise GitError("head search returned unsafe path")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise GitError("head search returned duplicate paths")
    return paths


def _parse_name_status(tokens: list[str]) -> list[tuple[str, str, str | None]]:
    """Validate the complete NUL-delimited diff stream before reading blobs."""
    if tokens == [""]:
        return []
    if not tokens or tokens[-1] != "":
        raise GitError("incomplete name-status stream")
    tokens = tokens[:-1]
    entries = []
    seen = set()
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if not re.fullmatch(r"(?:[ADMT]|[RCM](?:100|0?[0-9]{1,2}))", status):
            raise GitError("invalid diff status")
        code = status[0]
        count = 2 if code in "RC" else 1
        if i + count >= len(tokens):
            raise GitError("incomplete diff path record")
        paths = tokens[i + 1:i + count + 1]
        if any(not path or any(c in path for c in "\r\n\0") for path in paths):
            raise GitError("invalid diff path")
        path, old = (paths[1], paths[0]) if count == 2 else (paths[0], None)
        if path in seen:
            raise GitError("duplicate diff path")
        seen.add(path)
        entries.append((code, path, old))
        i += count + 1
    return entries


def list_range_changes(repo: str, base: str, head: str) -> list[FileChange]:
    base, head = resolve_commit(repo, base), resolve_commit(repo, head)
    out = _run(repo, ["diff", "--name-status", "-z", "--find-renames", base, head])
    entries = _parse_name_status([t for t in out.decode("utf-8", "strict").split("\0")])

    # Collect required sides, then fetch bounded OID batches per revision.
    specs: list[tuple[str, str]] = []
    for code, path, old in entries:
        if code == "R":
            specs += [(base, old), (head, path)]
        elif code == "C":
            specs.append((head, path))
        elif code == "A":
            specs.append((head, path))
        elif code == "D":
            specs.append((base, path))
        else:
            specs += [(base, path), (head, path)]
    # A side over the source byte limit is carried unread; the engine decides,
    # by the base-side roles, whether a detector must read it after all (#415).
    blobs = read_blobs(repo, specs, required=True, sides={base: "base", head: "head"},
                       unread_oversized=True)

    changes: list[FileChange] = []
    for code, path, old in entries:
        if code == "R":
            changes.append(
                _change(path, "modified", blobs.get((base, old)), blobs.get((head, path)), old_path=old)
            )
        elif code == "C":
            changes.append(_change(path, "added", None, blobs.get((head, path))))
        elif code == "A":
            changes.append(_change(path, "added", None, blobs.get((head, path))))
        elif code == "D":
            changes.append(_change(path, "deleted", blobs.get((base, path)), None))
        else:  # M, T, and anything else treated as modification
            changes.append(
                _change(path, "modified", blobs.get((base, path)), blobs.get((head, path)))
            )
    return changes


def _change(path: str, status: str, before, after, *, old_path: str | None = None) -> FileChange:
    """A FileChange whose unread sides keep no bytes and are listed (#415)."""
    unread = tuple(side for side in (before, after) if isinstance(side, UnreadSide))
    return FileChange(
        path, status,
        None if isinstance(before, UnreadSide) else before,
        None if isinstance(after, UnreadSide) else after,
        old_path=old_path, unread=unread,
    )


def list_worktree_changes(repo: str, *, base: str | None = None) -> list[FileChange]:
    """HEAD vs working tree (staged + unstaged + untracked)."""
    base = resolve_commit(repo, "HEAD" if base is None else base)
    entries = _worktree_status(repo, base)
    return _worktree_changes(repo, base, [(path, "D" in xy) for xy, path in entries])


def list_session_changes(repo: str, since: str) -> list[FileChange]:
    """A commit vs the working tree, for the Claude Code Stop hook (#418).

    `since` is the commit the session started from. The paths are those the
    commits since then changed (`git diff --name-only since HEAD`) and those
    `git status` lists against HEAD. Each change's before side is `since`'s
    blob; its after side is the working tree, or absent where status says
    deleted or a committed path is gone from HEAD.
    """
    since = resolve_commit(repo, since)
    head = resolve_commit(repo, "HEAD")
    committed = _committed_paths(repo, since, head)
    entries = _worktree_status(repo, head)
    listed = {path for _, path in entries}
    items = [(path, "D" in xy) for xy, path in entries]
    for path in committed:
        if path not in listed:
            # Clean in the working tree, so it holds HEAD's version or nothing.
            # Only presence is asked, so no prefix is streamed (#455).
            items.append((path, _read_blob(repo, head, path, side="head", unread_oversized=True,
                                           stream_prefix=False) is None))
    return _worktree_changes(repo, since, sorted(items))


def session_merge_base(repo: str, a: str, b: str) -> str | None:
    """`git merge-base a b`, or None when the two share no history (#418)."""
    try:
        proc = subprocess.run(["git", "-C", repo, "merge-base", a, b], capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("git read could not complete") from exc
    if proc.returncode == 1 and not proc.stdout and not proc.stderr:
        return None
    if proc.returncode != 0 or not re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", proc.stdout):
        raise GitError(f"git merge-base failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("ascii").strip()


def git_dir(repo: str) -> str:
    """The absolute Git directory of the work tree at `repo` (#418)."""
    raw = _run(repo, ["rev-parse", "--absolute-git-dir"])
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise GitError("git rev-parse returned an undecodable Git directory") from exc
    if not text.endswith("\n") or "\n" in text[:-1] or not os.path.isabs(text[:-1]):
        raise GitError("git rev-parse returned an unusable Git directory")
    return text[:-1]


def _committed_paths(repo: str, since: str, head: str) -> list[str]:
    # `--` ends the revisions: a working-tree file named like either commit
    # would otherwise make Git refuse the arguments as ambiguous.
    out = _run(repo, ["diff", "--name-only", "-z", "--no-renames", since, head, "--"])
    if len(out) > 64_000_000 or (out and not out.endswith(b"\0")):
        raise GitError("incomplete or over-budget diff path list")
    try:
        paths = out[:-1].decode("utf-8", "strict").split("\0") if out else []
    except UnicodeError as exc:
        raise GitError("undecodable diff path list") from exc
    if any(not path or any(c in path for c in "\r\n\0") for path in paths) or len(paths) != len(set(paths)):
        raise GitError("unsafe or duplicate diff path")
    return paths


def _worktree_status(repo: str, head: str) -> list[tuple[str, str]]:
    """`git status` records against `head`, which must stay HEAD throughout."""
    if resolve_commit(repo, "HEAD") != head:
        raise GitError("worktree HEAD changed before status collection")
    out = _run(repo, ["status", "--porcelain", "-z", "--untracked-files=all", "--no-renames"])
    if resolve_commit(repo, "HEAD") != head:
        raise GitError("worktree HEAD changed during status collection")
    if len(out) > 64_000_000 or (out and not out.endswith(b"\0")):
        raise GitError("incomplete or over-budget worktree status")
    try:
        tokens = out[:-1].decode("utf-8", "strict").split("\0") if out else []
    except UnicodeError as exc:
        raise GitError("undecodable worktree status") from exc
    entries = []
    seen = set()
    for token in tokens:
        if len(token) < 4 or token[2] != " ":
            raise GitError("incomplete worktree status record")
        xy, path = token[:2], token[3:]
        if xy != "??" and (not re.fullmatch(r"[ MTADU]{2}", xy) or xy == "  "):
            raise GitError("invalid worktree status code")
        if any(c in path for c in "\r\n\0") or path in seen:
            raise GitError("unsafe or duplicate worktree status path")
        seen.add(path)
        entries.append((xy, path))
    return entries


def _indexed_gitlink(repo: str, path: str) -> bool:
    """Only an exact, unmerged-free index gitlink can stand for no file.

    A dirty submodule is a directory in porcelain status, but its entry is
    a mode-160000 pointer, as in a commit tree. A directory or nested
    repository alone is not evidence of that mode. Literal pathspecs and
    the complete single-record match keep prefixes, globs and conflict
    stages from granting the same treatment.
    """
    raw = _run(repo, ["--literal-pathspecs", "ls-files", "--stage", "-z", "--", path])
    pattern = rb"160000 (?:[0-9a-f]{40}|[0-9a-f]{64}) 0\t" + re.escape(path.encode("utf-8")) + rb"\0"
    return re.fullmatch(pattern, raw) is not None


def _worktree_changes(repo: str, base: str, items: list[tuple[str, bool]]) -> list[FileChange]:
    """`base`'s blob against the working tree for each (path, deleted) item."""
    changes: list[FileChange] = []
    snapshot = WorkingTreeSnapshot(repo)
    for path, deleted in items:
        before = _read_blob(repo, base, path, side="base", unread_oversized=True)
        # Trust git's status codes over the filesystem: on a case-insensitive
        # volume, reading a deleted path back off disk returns the *renamed*
        # file's bytes, which made case-only test renames vanish entirely
        # (confirmed red-team finding).
        after: bytes | UnreadSide | None = None
        if not deleted:
            # Do not ask the regular-file reader to open a registered
            # submodule directory. Its checked-out files remain available
            # to the context snapshot; this only handles its pointer entry.
            # A base regular file replaced by a gitlink still has `before`
            # below, so its removal is not lost.
            try:
                directory = stat.S_ISDIR((snapshot.root / path).lstat().st_mode)
            except FileNotFoundError:
                directory = False
            if not (directory and _indexed_gitlink(repo, path)):
                after = snapshot.read(path, unread_oversized=True)
                if after is None:
                    raise GitError("status-present worktree source disappeared")
        if before is None and after is None:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            # Two unread sides cannot be compared; git status listed the path,
            # so it is carried as modified (#415).
            if before == after and not isinstance(before, UnreadSide):
                continue
            status = "modified"
        changes.append(_change(path, status, before, after))
    return _detect_worktree_renames(changes)


def _rename_content_key(data: bytes) -> bytes:
    """Use only textual CRLF equivalence, keeping original evidence untouched.

    Git can store LF blobs while checking out CRLF. Do not use lossy decoding,
    whitespace stripping, lone-CR normalization or binary equivalence here.
    """
    if b"\0" in data:
        return data
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return data.replace(b"\r\n", b"\n")


def _detect_worktree_renames(changes: list[FileChange]) -> list[FileChange]:
    """Pair equal delete+add halves, allowing textual CRLF/LF equivalence.

    `git status` is asked for --no-renames (its rename detection needs the
    index), so relocation would otherwise look like two unrelated events and
    slip past the rename handling in the engine — the round-1 git-mv fix was
    live only in range mode (confirmed red-team finding).
    """
    deleted = [c for c in changes if c.status == "deleted" and c.before is not None]
    added = [c for c in changes if c.status == "added" and c.after is not None]
    if not deleted or not added:
        return changes

    paired: dict[int, FileChange] = {}
    used_add: set[int] = set()
    by_content: dict[bytes, deque[FileChange]] = defaultdict(deque)
    for a in sorted(added, key=lambda c: c.path):
        by_content[_rename_content_key(a.after)].append(a)
    for d in sorted(deleted, key=lambda c: c.path):
        arrivals = by_content.get(_rename_content_key(d.before))
        if not arrivals:
            continue
        a = arrivals.popleft()
        used_add.add(id(a))
        paired[id(d)] = FileChange(
            path=a.path,
            status="modified",
            before=d.before,
            after=a.after,
            old_path=d.path,
        )

    result: list[FileChange] = []
    for c in changes:
        if id(c) in paired:
            result.append(paired[id(c)])
        elif id(c) in used_add:
            continue
        else:
            result.append(c)
    return result
