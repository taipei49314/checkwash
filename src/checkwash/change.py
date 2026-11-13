"""FileChange and EngineError — shared so roles/ci do not import engine."""

from __future__ import annotations

from dataclasses import dataclass, field

# The bytes `roles._shell_shebang` reads from the start of a side, and so the
# prefix an unread side keeps to answer it (#455).
SHEBANG_PREFIX_BYTES = 200


@dataclass(frozen=True)
class UnreadSide:
    """One side of a path over the source byte limit (#415).

    A snapshot asked to carry such a side hands this back instead of
    refusing. The diff then holds the path as changed with that side's bytes
    absent: no detector reads it and it earns no repair evidence. A path a
    detector must read refuses after all, with `refusal()`.

    `prefix` is the side's first SHEBANG_PREFIX_BYTES bytes when a snapshot
    read them, and None when it did not (#455). It answers one question:
    does the side start with a shell shebang? Those bytes decide it exactly
    as the whole side would. It never reaches a parser, a runner-content
    check, repair evidence or any output, and it takes no part in equality,
    hashing or the repr: a side is the same side with or without it.
    """

    path: str
    side: str  # "base", "head" or "worktree"
    size: int
    limit: int
    prefix: bytes | None = field(default=None, compare=False, repr=False)

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


@dataclass(frozen=True)
class LinkSide:
    """A virtual environment's own link that a working-tree run carries unfollowed (D-208).

    Git lists the path as untracked, no compared commit holds the environment
    directory, and on disk the path is a symbolic link directly in the
    environment's `bin` or `Scripts` directory (not ending in `.py` in any
    case), or its `lib64` link to `lib` beside a directory `lib`. The
    environment is a directory other than the repository root that holds
    `pyvenv.cfg` as a regular file. The diff holds the path with no bytes on
    either side, since nothing follows a link: a path a detector must read, or
    an environment pytest's collection can reach, refuses with `refusal()`,
    and any other is set aside with `note()`.
    """

    path: str
    environment: str

    def described(self) -> str:
        """`path` in the virtual environment `environment`, each as is unless it
        would not print on one line (#346)."""
        path = self.path if self.path.isprintable() else repr(self.path)
        environment = self.environment if self.environment.isprintable() else repr(self.environment)
        return f"{path} in the virtual environment {environment}"

    def note(self) -> str:
        """The stderr note for a link set aside."""
        return f"skipped the link {self.described()}, which checkwash does not follow"

    def refusal(self, reason: str = "a detector must read this path") -> EngineError:
        """The engine error for a link the engine cannot set aside."""
        return EngineError(f"strict snapshot cannot read the link {self.described()}: checkwash does "
                           f"not follow a link, and {reason}")


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
    # A virtual environment's own link (D-208): both sides are None.
    links: tuple[LinkSide, ...] = ()


class EngineError(Exception):
    pass


class SourceOverLimit(EngineError):
    """A size refusal; `unread` names the path, side, size and limit (#415)."""

    def __init__(self, unread: UnreadSide):
        super().__init__(unread.message())
        self.unread = unread


class SearchHitLimit(EngineError):
    """A snapshot search reached its hit limit, so its answer may be truncated.

    It stays an engine error for every caller that does not handle it. Only
    the expected-value importer pass sets such a search aside: in a run that
    reports it, searched by one helper name with the paths the diff changes
    left out, unless the diff renamed a helper to that name (D-206).
    """
