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


def _read_blob(repo: str, rev: str, path: str) -> bytes | None:
    try:
        return _run(repo, ["show", f"{rev}:{path}"])
    except GitError:
        return None


def read_base_file(repo: str, base: str, path: str) -> bytes | None:
    return _read_blob(repo, base, path)


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
        disk = os.path.join(repo, path.replace("/", os.sep))
        after: bytes | None
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
    return changes
