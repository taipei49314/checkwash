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


def grep_head_paths(repo: str, rev: str, needles: list[str]) -> list[str]:
    """Paths at `rev` whose content contains any needle (fixed strings).

    One subprocess for the whole batch; used by the duplicate-unit search to
    find surviving copies of deleted tests without reading the tree. git grep
    exits 1 on no match, which is an answer, not an error.
    """
    if not needles:
        return []
    args = ["grep", "-l", "-F"]
    for needle in needles:
        args += ["-e", needle]
    args.append(rev)
    try:
        out = _run(repo, args)
    except GitError:
        return []
    paths = []
    for line in out.decode("utf-8", "replace").split("\n"):
        if ":" in line:
            paths.append(line.split(":", 1)[1])
    return paths


def list_range_changes(repo: str, base: str, head: str) -> list[FileChange]:
    out = _run(repo, ["diff", "--name-status", "-z", "--find-renames", base, head])
    tokens = [t for t in out.decode("utf-8", "replace").split("\0")]
    changes: list[FileChange] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if not status:
            i += 1
            continue
        code = status[0]
        if code in ("R", "C"):
            old, new = tokens[i + 1], tokens[i + 2]
            i += 3
            changes.append(
                FileChange(
                    path=new,
                    status="modified" if code == "R" else "added",
                    before=_read_blob(repo, base, old) if code == "R" else None,
                    after=_read_blob(repo, head, new),
                    old_path=old if code == "R" else None,
                )
            )
        else:
            path = tokens[i + 1]
            i += 2
            if code == "A":
                changes.append(FileChange(path, "added", None, _read_blob(repo, head, path)))
            elif code == "D":
                changes.append(FileChange(path, "deleted", _read_blob(repo, base, path), None))
            else:  # M, T, and anything else treated as modification
                changes.append(
                    FileChange(
                        path,
                        "modified",
                        _read_blob(repo, base, path),
                        _read_blob(repo, head, path),
                    )
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
