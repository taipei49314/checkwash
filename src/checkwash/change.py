"""FileChange and EngineError — shared so roles/ci do not import engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnreadSide:
    """One side of a path over the source byte limit (#415).

    A snapshot asked to carry such a side hands this back instead of
    refusing. The diff then holds the path as changed with that side's bytes
    absent: no detector reads it and it earns no repair evidence. A path a
    detector must read refuses after all, with `refusal()`.
    """

    path: str
    side: str  # "base", "head" or "worktree"
    size: int
    limit: int

    def described(self) -> str:
        """`path (side, size > limit bytes)`; the path as is, unless it would
        not print on one line (#346)."""
        shown = self.path if self.path.isprintable() else repr(self.path)
        return f"{shown} ({self.side}, {self.size} > {self.limit} bytes)"

    def message(self) -> str:
        """The size refusal, naming path, side, size and limit."""
        return f"strict snapshot source exceeds the byte limit: {self.described()}"

    def refusal(self) -> SourceOverLimit:
        return SourceOverLimit(self)

    def note(self) -> str:
        """The stderr note for a side carried unread."""
        return f"not read, over the source byte limit: {self.described()}; it earns no repair evidence"


@dataclass
class FileChange:
    path: str  # forward-slash normalized
    status: str  # added | modified | deleted
    before: bytes | None
    after: bytes | None
    old_path: str | None = None  # set for git renames (R status)
    synthetic: str | None = None  # marks halves of an expanded rename
    # Sides carried unread (#415); `before`/`after` is None for each of them.
    unread: tuple[UnreadSide, ...] = ()


class EngineError(Exception):
    pass


class SourceOverLimit(EngineError):
    """A size refusal; `unread` names the path, side, size and limit (#415)."""

    def __init__(self, unread: UnreadSide):
        super().__init__(unread.message())
        self.unread = unread
