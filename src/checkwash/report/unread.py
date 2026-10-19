"""Unread sides in the findings JSON, SARIF and term reports (#454).

A changed side over the source byte limit that no detector must read is
carried unread, and its whole change is set aside before any pass (#415).
Its stderr note used to be the only trace, so a consumer of the machine
output could not tell a pass that never read a file from one that read
every file. The json, sarif and term writers now name each such side with
the four facts of that note: path, side, size and limit. hook-json and
`--emit-ir` do not (#454 ruling, item 6).
"""

from __future__ import annotations

from collections.abc import Iterable

from checkwash.change import UnreadSide


def sorted_unread(sides: Iterable[UnreadSide]) -> list[UnreadSide]:
    """`sides` by path, then side, never in the order of the diff.

    Range mode lists changes in Git's order and worktree mode in status
    order plus rename pairing, so each writer sorts for itself.
    """
    return sorted(sides, key=lambda side: (side.path, side.side))


def unread_entry(side: UnreadSide) -> dict[str, object]:
    """The JSON entry for one unread side: exactly `path`, `side`, `size`, `limit`.

    An explicit projection, never `to_jsonable(side)`, which would write
    every dataclass field: the bounded prefix #455 stores on the side must
    stay out of machine output. The four keys are the stderr note's, so
    entries and notes match one to one. #456 (d) can reuse this entry for
    the side an exit-2 run refused; nothing here emits it for a refusal.
    """
    return {"path": side.path, "side": side.side, "size": side.size, "limit": side.limit}


def unread_entries(sides: Iterable[UnreadSide]) -> list[dict[str, object]]:
    """The findings JSON `unread` list: one entry per side, sorted by path, then side."""
    return [unread_entry(side) for side in sorted_unread(sides)]
