"""Git plumbing access. git is the only external binary greenwash talks to.

The head side may be attacker-controlled; nothing here executes repo content.
"""

from __future__ import annotations

import os
import subprocess

from greenwash.engine import FileChange


class GitError(Exception):
    pass


def _run(repo: str, args: list[str]) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args[:2])} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def rev_parse(repo: str, rev: str) -> str:
    return _run(repo, ["rev-parse", "--short", rev]).decode("ascii").strip()


def merge_base(repo: str, a: str, b: str) -> str:
    return _run(repo, ["merge-base", a, b]).decode("ascii").strip()


def _read_blob(repo: str, rev: str, path: str) -> bytes | None:
    try:
        return _run(repo, ["show", f"{rev}:{path}"])
    except GitError:
        return None


def read_base_file(repo: str, base: str, path: str) -> bytes | None:
    return _read_blob(repo, base, path)


def read_blobs(repo: str, specs: list[tuple[str, str]]) -> dict[tuple[str, str], bytes | None]:
    """Every requested blob, in one `git cat-file --batch` process.

    `_read_blob` spawns a process per blob, and a range diff needs two per
    modified file. Measured on pydantic: a 120-file commit spent 9.1 s in 241
    `git show` calls, 58% of its wall clock — and the perf gate could not see
    any of it, because it calls `analyze()` with in-memory changes and never
    touches git (field integration 2026-08-07). Batching is the same bytes in
    one process.

    The batch protocol answers requests in order, either
    `<oid> <type> <size>\\n<content>\\n` or `<request> missing\\n`. Anything
    unparseable falls back to the per-blob path rather than guessing, so a
    surprising response degrades to slow rather than wrong.
    """
    if not specs:
        return {}
    uniq = sorted(set(specs))
    stdin_specs: list[tuple[str, str]] = []
    result: dict[tuple[str, str], bytes | None] = {}
    for s in uniq:
        if "\n" in s[0] or "\n" in s[1]:
            # A newline inside a spec becomes two protocol requests; git's
            # extra `<fragment> missing` response is then consumed as the
            # next spec's header, and when the response count happens to
            # realign the loop below completes with WRONG assignments and no
            # fallback — an existing file's blob reads as None and its
            # weakenings vanish silently (audit 2026-08-19, verified at
            # protocol level with the real binary; Git-for-Windows refuses
            # such paths outright, so the entry arrives in Linux-authored
            # trees). Rejected here as missing: the file stays visible as
            # unreadable rather than poisoning its neighbours.
            result[s] = None
        else:
            stdin_specs.append(s)
    if not stdin_specs:
        return result
    stdin = b"".join(f"{rev}:{path}\n".encode("utf-8") for rev, path in stdin_specs)
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "cat-file", "--batch"],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc

    out, pos = proc.stdout, 0
    for spec in stdin_specs:
        end = out.find(b"\n", pos)
        if end < 0:
            result.update({s: _read_blob(repo, *s) for s in stdin_specs if s not in result})
            return result
        header = out[pos:end]
        pos = end + 1
        if header.endswith(b" missing") or header.endswith(b" ambiguous"):
            result[spec] = None
            continue
        parts = header.rsplit(b" ", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            result.update({s: _read_blob(repo, *s) for s in stdin_specs if s not in result})
            return result
        size = int(parts[1])
        result[spec] = out[pos : pos + size]
        pos += size + 1  # content is followed by a newline
    return result


def grep_head_paths(repo: str, rev: str, needles: list[str]) -> list[str]:
    """Paths at `rev` whose content contains any needle (fixed strings).

    One subprocess for the whole batch; used by the duplicate-unit search to
    find surviving copies of deleted tests without reading the tree. git grep
    exits 1 on no match, which is an answer, not an error.

    `-z` keeps the `rev:path` record shape but NUL-terminates it and — the
    load-bearing half — disables path quoting. With the default
    `core.quotepath`, any non-ASCII path came back C-quoted
    (`"tests/test_\\346\\213\\267\\350\\262\\235.py"`), failed the role
    filter downstream, and the duplicate-survivor search never found
    CJK-named copies: a false block for exactly the repositories most likely
    to have them (audit 2026-08-19). Format verified against the real binary:
    one record per match, first-colon split, path bytes verbatim UTF-8.
    """
    if not needles:
        return []
    args = ["grep", "-l", "-F", "-z"]
    for needle in needles:
        args += ["-e", needle]
    args.append(rev)
    try:
        out = _run(repo, args)
    except GitError:
        return []
    paths = []
    for tok in out.split(b"\0"):
        if b":" in tok:
            paths.append(tok.split(b":", 1)[1].decode("utf-8", "replace"))
    return paths


def _parse_name_status(tokens: list[str]) -> list[tuple[str, str, str | None]]:
    """(code, path, old_path) for each entry of a -z name-status stream."""
    entries: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if not status:
            i += 1
            continue
        code = status[0]
        if code in ("R", "C"):
            entries.append((code, tokens[i + 2], tokens[i + 1]))
            i += 3
        else:
            entries.append((code, tokens[i + 1], None))
            i += 2
    return entries


def list_range_changes(repo: str, base: str, head: str) -> list[FileChange]:
    out = _run(repo, ["diff", "--name-status", "-z", "--find-renames", base, head])
    entries = _parse_name_status([t for t in out.decode("utf-8", "replace").split("\0")])

    # Collect every blob this diff needs, then fetch them in one process.
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
    blobs = read_blobs(repo, specs)

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
    tokens = out.decode("utf-8", "replace").split("\0")
    changes: list[FileChange] = []
    for token in tokens:
        if len(token) < 4:
            continue
        xy, path = token[:2], token[3:]
        before = _read_blob(repo, "HEAD", path)
        # Trust git's status codes over the filesystem: on a case-insensitive
        # volume, reading a deleted path back off disk returns the *renamed*
        # file's bytes, which made case-only test renames vanish entirely
        # (confirmed red-team finding).
        deleted = "D" in xy
        after: bytes | None = None
        if not deleted:
            disk = os.path.join(repo, path.replace("/", os.sep))
            try:
                with open(disk, "rb") as fh:
                    after = fh.read()
            except OSError:
                after = None
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
