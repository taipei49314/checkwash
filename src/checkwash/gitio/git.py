"""Git plumbing access. git is the only external binary checkwash talks to.

The head side may be attacker-controlled; nothing here executes repo content.
"""

from __future__ import annotations

import re
import subprocess

from checkwash.change import EngineError, FileChange
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot


class GitError(Exception):
    pass


def _run(repo: str, args: list[str]) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("git read could not complete") from exc
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args[:2])} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def rev_parse(repo: str, rev: str) -> str:
    return _run(repo, ["rev-parse", "--short", rev]).decode("ascii").strip()


def merge_base(repo: str, a: str, b: str) -> str:
    return _run(repo, ["merge-base", a, b]).decode("ascii").strip()


def resolve_commit(repo: str, rev: str) -> str:
    raw = _run(repo, ["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"])
    if not re.fullmatch(b"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", raw):
        raise GitError("invalid resolved commit identity")
    return raw.decode("ascii").strip()


def _read_blob(repo: str, rev: str, path: str) -> bytes | None:
    try:
        return GitSnapshot(repo, rev).read(path)
    except EngineError as exc:
        raise GitError(str(exc)) from exc


def read_base_file(repo: str, base: str, path: str) -> bytes | None:
    return _read_blob(repo, base, path)


def read_blobs(repo: str, specs: list[tuple[str, str]], *, required=False) -> dict[tuple[str, str], bytes | None]:
    """Read exact inventoried OIDs in bounded batches, preserving failures.

    GitSnapshot separates tree absence (and explicit opaque gitlink entries)
    from failed blob reads. It validates process status, ordered headers,
    sizes, delimiters and content identities; no permissive fallback is used.
    """
    grouped: dict[str, list[str]] = {}
    for revision, path in sorted(set(specs)):
        grouped.setdefault(revision, []).append(path)
    result = {}
    try:
        for revision, paths in grouped.items():
            snapshot = GitSnapshot(repo, revision)
            blobs = snapshot.read_many(paths)
            if required and any(data is None and path not in snapshot._opaque for path, data in blobs.items()):
                raise GitError("required diff side is absent from its tree")
            result.update({(revision, path): data for path, data in blobs.items()})
    except EngineError as exc:
        raise GitError(str(exc)) from exc
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
    if proc.returncode != 0:
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
    blobs = read_blobs(repo, specs, required=True)

    changes: list[FileChange] = []
    for code, path, old in entries:
        if code == "R":
            changes.append(
                FileChange(path, "modified", blobs.get((base, old)), blobs.get((head, path)), old_path=old)
            )
        elif code == "C":
            changes.append(FileChange(path, "added", None, blobs.get((head, path))))
        elif code == "A":
            changes.append(FileChange(path, "added", None, blobs.get((head, path))))
        elif code == "D":
            changes.append(FileChange(path, "deleted", blobs.get((base, path)), None))
        else:  # M, T, and anything else treated as modification
            changes.append(
                FileChange(path, "modified", blobs.get((base, path)), blobs.get((head, path)))
            )
    return changes


def list_worktree_changes(repo: str) -> list[FileChange]:
    """HEAD vs working tree (staged + unstaged + untracked)."""
    out = _run(repo, ["status", "--porcelain", "-z", "--untracked-files=all", "--no-renames"])
    tokens = out.decode("utf-8", "strict").split("\0")
    changes: list[FileChange] = []
    base = resolve_commit(repo, "HEAD")
    snapshot = WorkingTreeSnapshot(repo)
    for token in tokens:
        if len(token) < 4:
            continue
        xy, path = token[:2], token[3:]
        before = _read_blob(repo, base, path)
        # Trust git's status codes over the filesystem: on a case-insensitive
        # volume, reading a deleted path back off disk returns the *renamed*
        # file's bytes, which made case-only test renames vanish entirely
        # (confirmed red-team finding).
        deleted = "D" in xy
        after: bytes | None = None
        if not deleted:
            after = snapshot.read(path)
            if after is None:
                raise GitError("status-present worktree source disappeared")
        if before is None and after is None:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            if before == after:
                continue
            status = "modified"
        changes.append(FileChange(path=path, status=status, before=before, after=after))
    return _detect_worktree_renames(changes)


def _detect_worktree_renames(changes: list[FileChange]) -> list[FileChange]:
    """Pair identical delete+add halves into renames.

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
    for d in sorted(deleted, key=lambda c: c.path):
        for a in sorted(added, key=lambda c: c.path):
            if id(a) in used_add or a.after != d.before:
                continue
            used_add.add(id(a))
            paired[id(d)] = FileChange(
                path=a.path,
                status="modified",
                before=d.before,
                after=a.after,
                old_path=d.path,
            )
            break

    result: list[FileChange] = []
    for c in changes:
        if id(c) in paired:
            result.append(paired[id(c)])
        elif id(c) in used_add:
            continue
        else:
            result.append(c)
    return result
