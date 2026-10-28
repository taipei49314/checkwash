"""Claude Code PreToolUse: ask before an Edit or Write weakens a test (0.11, D-189).

The managed PreToolUse handler (`checkwash hook pre-tool-use`) predicts what
one Edit or Write would leave on disk, analyses that single change against the
working tree as it is now, with policy from the session base as the Stop hook
reads it (#418) and `oracle_freeze` on, and asks the user when the change
weakens a test under one of WEAKENING_RULES at high or above. The 2026-10-28
replay of 630 real agent edits measured this shape: it asked on about one test
edit in ten.

Every answer here is a prediction from the documented tool input: the path the
call writes, spelled as `git status` spells it, and the bytes it would leave
there. Anything not predicted exactly is None, and the hook leaves the call to
the normal permission flow; the Stop hook reads what was actually written. The
hook is advisory, like the Stop hook: edits made through Bash or any tool the
matcher does not name never reach it, and the required CI check stays the gate.
"""

from __future__ import annotations

import os
from pathlib import Path

from checkwash.change import SHEBANG_PREFIX_BYTES, EngineError, FileChange, UnreadSide
from checkwash.gitio.snapshot import _SKIP, MAX_SEARCH_HITS, MAX_SOURCE_BYTES, WorkingTreeSnapshot
from checkwash.roles import collectable

TOOLS = ("Edit", "Write", "MultiEdit")
# The rules the ask is for: each says a test now checks less than before. The
# expectation rules (EXPECTED_VALUE_CHANGED and its family) are left to the
# Stop hook and CI: in the replay they asked 43 times and found two
# unexplained loosenings, so asking there was nearly all interruption.
WEAKENING_RULES = frozenset({
    "ASSERT_WEAKENED", "ASSERT_REMOVED", "TEST_DISABLED", "TOLERANCE_LOOSENED", "BROAD_EXCEPT_ADDED",
})
# A Write carries the whole file, at most twice MAX_SOURCE_BYTES once JSON
# escapes it, plus an Edit's two strings. Larger input is not read further.
INPUT_BYTE_CAP = 8_000_000
# The tool call waits for the hook. Past this the edit goes ahead unanalysed,
# under the base policy's on_engine_error, rather than stall the agent.
DEADLINE_SECONDS = 30.0
_REASON_FINDINGS = 3
_REASON_MAX_CHARS = 1200


def is_judged_test(config, rel: str) -> bool:
    """A Python path the engine judges as a test (engine.py's role pass).

    The table role, test or conftest, or a file pytest's default collection
    runs (`collectable`, #219). JS/TS tests are not asked about in 0.11: the
    replay measured Python test edits only.
    """
    return rel.endswith(".py") and (config.role_of(rel) in ("test", "conftest") or collectable(rel))


def repository_path(root: str, file_path: object, cwd: object = None) -> str | None:
    """The repository-relative path a tool call writes, or None.

    Resolved the way the write resolves it, through links and junctions, so a
    path spelled through a link into a test file is that test file. None for a
    path outside this work tree, inside `.git`, inside a nested repository or
    submodule (this work tree's status does not list it), an alternate data
    stream, or one that is not a plain UTF-8 path.
    """
    if not isinstance(file_path, str) or not file_path or any(c in file_path for c in "\0\r\n"):
        return None
    try:
        file_path.encode("utf-8")
    except UnicodeEncodeError:
        return None
    path = Path(file_path)
    if not path.is_absolute():
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            return None
        path = Path(cwd, file_path)
    try:
        base = Path(root).resolve()
        target = Path(os.path.realpath(path))
        parts = list(target.relative_to(base).parts)
    except (OSError, RuntimeError, ValueError):
        return None
    if os.name == "nt":
        # Windows creates `test_x.py.` and `test_x.py ` as `test_x.py`.
        parts = [part.rstrip(" .") for part in parts]
    if not parts or any(not part or part == ".git" or ":" in part for part in parts):
        return None
    current = base
    for part in parts[:-1]:
        current = current / part
        if os.path.lexists(current / ".git"):
            return None
    return "/".join(parts)


def proposed_bytes(tool: str, tool_input: dict, before: bytes | None) -> bytes | None:
    """The bytes the call would leave at its path, or None when not predicted.

    An Edit applies old_string to new_string as the tool does: exactly once,
    or every time with replace_all; no match, or more than one without
    replace_all, fails the call, so there is nothing to ask about. A file
    whose every line ends in CRLF is matched with CRLF line ends.
    """
    if tool == "Write":
        content = tool_input.get("content")
        return _encode(content) if isinstance(content, str) else None
    edits = [tool_input] if tool == "Edit" else tool_input.get("edits")  # MultiEdit: undocumented
    if not isinstance(edits, list) or not edits:
        return None
    try:
        text = None if before is None else before.decode("utf-8")
    except UnicodeDecodeError:
        return None
    crlf = text is not None and "\r\n" in text and "\n" not in text.replace("\r\n", "")
    for edit in edits:
        if not isinstance(edit, dict):
            return None
        old, new, every = edit.get("old_string"), edit.get("new_string"), edit.get("replace_all", False)
        if not isinstance(old, str) or not isinstance(new, str) or not isinstance(every, bool) or old == new:
            return None
        if crlf:
            old, new = (s.replace("\r\n", "\n").replace("\n", "\r\n") for s in (old, new))
        if not old:
            if text:  # an empty old_string only creates a file
                return None
            text = new
            continue
        if text is None:
            return None
        count = text.count(old)
        if count == 0 or (count > 1 and not every):
            return None
        text = text.replace(old, new, -1 if every else 1)
    return _encode(text)


def _encode(text: str | None) -> bytes | None:
    if text is None:
        return None
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate from the JSON input
        return None


def writes_python(file_path: str) -> bool:
    """The gate before any Git call: would this write land in a `.py` file?

    On Windows the file system folds case and drops a last part's trailing
    dots and spaces, so `test_x.PY` and `test_x.py.` write `test_x.py`.
    """
    if os.name == "nt":
        return file_path.rstrip(" .").lower().endswith(".py")
    return file_path.endswith(".py")


def parses(data: bytes) -> bool:
    """Whether the engine's Python frontend parses these bytes, as it decodes them."""
    from checkwash.frontends.python.frontend import normalize_source
    from checkwash.frontends.python.syntax import parse_module

    try:
        parse_module(normalize_source(data))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    return True


def proposed_change(path: str, before: bytes | None, after: bytes) -> FileChange:
    """One change, both sides in memory: callers ask about oversized sides first."""
    return FileChange(path, "added" if before is None else "modified", before, after)


class ProposedTree(WorkingTreeSnapshot):
    """The working tree with one path holding the bytes a tool call would write.

    Every other path is read from disk with the snapshot's own admission
    checks, so the conftest chain, importer search, collection inventory and
    runtime-shadow passes all see the proposed content.
    """

    def __init__(self, repo, change: FileChange):
        super().__init__(repo, side="proposed")
        self.path = change.path
        self.proposed = change.after
        self.created = not os.path.lexists(self.root / self.path)

    def read(self, path, *, unread_oversized=False):
        if path.replace("\\", "/") != self.path:
            return super().read(path, unread_oversized=unread_oversized)
        return self.proposed

    def list_paths(self):
        paths = super().list_paths()
        return sorted([*paths, self.path]) if self.created else paths

    def config_modes(self, paths):
        modes = super().config_modes(paths)
        if self.created and self.path in modes and modes[self.path] is None:
            modes[self.path] = b"100644"
        return modes

    def search(self, needles):
        hits = super().search(needles)  # an existing `path` is read through read()
        if not self.created or not needles or not self.path.endswith(".py"):
            return hits
        if "" not in needles and any(d in _SKIP or d.startswith(".") for d in self.path.split("/")[:-1]):
            return hits
        data = self.proposed
        if data and ("" in needles or any(n.encode("utf-8") in data for n in needles)):
            hits.append(self.path)
            if len(hits) >= MAX_SEARCH_HITS:
                raise EngineError("strict snapshot importer search exceeds the hit limit")
        return hits


def oversized(rel: str, before, after: bytes) -> UnreadSide | None:
    """The side over the source byte limit, or None (#415, #456).

    Such an edit cannot be analysed, and the padding route (write a weakened
    test past the limit, then edit the padding away) would pass silently, so
    the hook asks instead, as the Stop hook blocks (#456).
    """
    if isinstance(before, UnreadSide):
        return before
    if len(after) > MAX_SOURCE_BYTES:
        return UnreadSide(rel, "proposed", len(after), MAX_SOURCE_BYTES, prefix=after[:SHEBANG_PREFIX_BYTES])
    return None


# Bidirectional embeddings, overrides and isolates: printable, yet they reorder
# what the user reads in the prompt. Built from code points, so this source
# holds none of them (HIDDEN_UNICODE).
_BIDI_CONTROLS = frozenset(map(chr, (*range(0x202A, 0x202F), *range(0x2066, 0x206A))))


def _shown(text: str) -> str:
    """One printable line: agent-written names reach the user's prompt."""
    return "".join(c if c.isprintable() and c not in _BIDI_CONTROLS
                   else f"\\u{ord(c):04x}" for c in text)


def _footer() -> str:
    return ("Approve only if the weaker test is intended. If you deny it, Claude should report the "
            "finding to you, not make the same change another way.")


def weakening_reason(found: list) -> str:
    """The permission prompt's text: for the user, and for Claude after a -p deny."""
    listed = "; ".join(
        f"{f.rule} {f.path}" + (f" :: {f.unit}" if f.unit else "") + f" — {f.message}"
        for f in found[:_REASON_FINDINGS]
    ) + (f"; and {len(found) - _REASON_FINDINGS} more" if len(found) > _REASON_FINDINGS else "")
    head = f"checkwash: this edit weakens a test ({len(found)} finding(s)): "
    room = _REASON_MAX_CHARS - len(head) - len(_footer()) - 2
    listed = _shown(listed)
    if len(listed) > room:
        listed = listed[: max(room - 1, 0)] + "…"
    return head + listed + ". " + _footer()


def oversized_reason(side: UnreadSide) -> str:
    return _shown(f"checkwash: this edit was not analysed: {side.described()} is over the source byte "
                  "limit, so a weakened test in it would not be seen. ") + _footer()


def unanalysed_reason(rel: str, detail: str) -> str:
    return _shown(f"checkwash: this edit to {rel} was not analysed before it was made, so it was neither "
                  f"asked about nor passed. Engine error: {detail}")[:_REASON_MAX_CHARS]


def ask(reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason,
    }}
