"""Finding model and versioned fingerprints (checkwash_findings_version 2)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from checkwash.change import EngineError
from checkwash.ir.model import FileIR, normalize_text

CHANGE_FINGERPRINT_RULES = frozenset({
    "GUARDRAIL_TOUCHED", "CI_WORKFLOW_TOUCHED", "TEST_FILE_UNPARSEABLE", "SCOPE_DRIFT",
    "SNAPSHOT_CODE_COCHANGE",
})
# The assertion-level oracle namespaces with content-bound v2 identities
# (#421, ruling Q2 (b)): a different after state on the same before needs a
# different approval. EXPECTED_VALUE_HARDCODED, CONFTEST_PATCHES_PROD,
# TEST_PATCHES_SUBJECT and the non-oracle rules keep their legacy keys.
ASSERTION_FINGERPRINT_RULES = frozenset({
    "ASSERT_WEAKENED", "ASSERT_SUBSTITUTED", "TOLERANCE_LOOSENED", "EXPECTED_VALUE_CHANGED",
    "EXPECTED_VALUE_DERIVED", "EXPECTATION_DEFINITION_CHANGED", "SUBJECT_NORMALIZED",
    "SUBJECT_INPUT_CHANGED", "ASSERT_REMOVED",
})
# Round 2 of #421, under its own ruling (#512, Q2 and Q3 (a)): every
# TEST_DISABLED shape has a key of the same form, `rule/path/unit/v2:<64hex>`,
# built as the nine rules' keys are, and its legacy keys are retired the same
# way. A set of its own, so the nine rules' set stays the one #421 ruled.
TEST_DISABLED_FINGERPRINT_RULES = frozenset({"TEST_DISABLED"})
_UNIT_FINGERPRINT_RULES = ASSERTION_FINGERPRINT_RULES | TEST_DISABLED_FINGERPRINT_RULES
_CHANGE_DIGEST = re.compile(r"v2:[0-9a-f]{64}\Z")
_CONTENT_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def fingerprint_state(fingerprint: str, rule: str | None = None) -> str:
    """`supported`, `retired`, or `invalid`; independent of entry expiry."""
    key_rule = fingerprint.split("/", 1)[0]
    parts = fingerprint.split("/", 1)[1].rsplit("/", 2) if "/" in fingerprint else []
    # Stored expectations are a file-scoped variant of an existing oracle
    # rule. Assertion-level EXPECTED_VALUE_CHANGED identities stay compatible.
    stored_expectation = (
        key_rule == "EXPECTED_VALUE_CHANGED"
        and fingerprint.rsplit("/", 1)[-1].startswith("v2:")
        and len(parts) == 3 and parts[1] == "-"
    )
    if key_rule in _UNIT_FINGERPRINT_RULES and not stored_expectation:
        # Assertion-level: `rule/path/unit/v2:<64hex>`. A JS unit is the raw
        # test title, which may hold `/` anywhere, even last (`it("GET /")`),
        # so only the last segment is read as the digest, after a non-empty
        # path and unit. A legacy before-only key is retired: still parsed,
        # never eligible (#421 Q4 (a)). TEST_DISABLED's keys have the same
        # form, its file-level focus under the unit `<file>`, and its legacy
        # keys are retired the same way (#512 Q3 (a)).
        middle, _, last = (fingerprint.split("/", 1)[1] if "/" in fingerprint else "").rpartition("/")
        path, _, unit = middle.partition("/")
        if not path or not unit:
            return "invalid"
        if not last.startswith("v2:"):
            return "retired"
        if not _CHANGE_DIGEST.fullmatch(last):
            return "invalid"
        if rule and rule != key_rule:
            return "invalid"
        return "supported"
    if key_rule in CHANGE_FINGERPRINT_RULES or stored_expectation:
        if len(parts) != 3 or not parts[0] or parts[1] != "-":
            return "invalid"
        if not parts[2].startswith("v2:"):
            return "retired"
        if not _CHANGE_DIGEST.fullmatch(parts[2]):
            return "invalid"
        if rule and rule != key_rule:
            return "invalid"
    return "supported"


def is_content_bound_fingerprint(fingerprint: str, rule: str | None = None) -> bool:
    """Recognize supported v2 identities, including stored-expectation variants."""
    key_rule = fingerprint.split("/", 1)[0]
    return (
        key_rule in CHANGE_FINGERPRINT_RULES | _UNIT_FINGERPRINT_RULES
        and bool(_CHANGE_DIGEST.fullmatch(fingerprint.rsplit("/", 1)[-1]))
        and fingerprint_state(fingerprint, rule) == "supported"
    )


def fingerprint_issue(fingerprint: str, rule: str | None = None) -> str | None:
    """Explain an unsupported exemption key without discarding its record.

    The fingerprint's own rule is authoritative: changing an entry's `rule`
    field must not make a retired file-wide key eligible again. Other rules
    keep their existing identity scheme.
    """
    key_rule = fingerprint.split("/", 1)[0]
    state = fingerprint_state(fingerprint, rule)
    if state == "supported":
        return None
    if state == "retired" and key_rule in ASSERTION_FINGERPRINT_RULES:
        return (
            f"{key_rule} requires a content-bound v2 fingerprint; legacy before-only "
            "exemptions are retired, because they also covered every other rewrite "
            "of the same line (#421). Re-run the reviewed diff with this version and "
            "review its new fingerprint before recording an exemption"
        )
    if state == "retired" and key_rule in TEST_DISABLED_FINGERPRINT_RULES:
        return (
            f"{key_rule} requires a content-bound v2 fingerprint; legacy exemptions are "
            "retired, because one approved skip, guard change or parametrize row deletion "
            "also covered later, different changes to the same unit (#512). Re-run the "
            "reviewed diff with this version and review its new fingerprint before "
            "recording an exemption"
        )
    if state == "retired":
        return (
            f"{key_rule} requires a content-bound v2 fingerprint; legacy file-wide "
            "exemptions are retired. Re-run the reviewed diff with this version "
            "and review its new fingerprint before recording an exemption"
        )
    if rule and rule != key_rule:
        return f"entry rule {rule!r} does not match fingerprint rule {key_rule!r}"
    return f"{key_rule} requires a complete content-bound v2 fingerprint from a reviewed diff"

# TEST_DISABLED event kinds. Gating must read `Finding.shape`, never English
# message text (E2 / static review 2026-08-11 Issue 3).
SHAPE_UNIT_REMOVED = "unit_removed"
SHAPE_MARKER_ADDED = "marker_added"
SHAPE_COLLECTION_CONTROL = "collection_control"
SHAPE_GUARD_WEAKENED = "guard_weakened"
SHAPE_PARAM_CASES_REMOVED = "param_cases_removed"
# A mark pytest never reads: a `pytestmark` in conftest.py, which pytest does
# not collect as a test module. It disables nothing (#209 Q3), and neither
# does its guard: a guard made always true or removed there has this shape
# too (#260).
SHAPE_INERT_MARK = "inert_mark"


@dataclass
class Evidence:
    text: str
    span: tuple[int, int]


@dataclass
class Finding:
    rule: str
    severity: str  # info | warn | high | critical
    message: str
    path: str
    unit: str | None
    before: Evidence | None = None
    after: Evidence | None = None
    escalators: list[str] = field(default_factory=list)
    deescalators: list[str] = field(default_factory=list)
    fingerprint: str = ""
    allowlisted: bool = False
    # ASSERT_WEAKENED only: how far the strength fell and where it landed,
    # so gating can distinguish material weakening from style drift.
    strength_drop: int | None = None
    strength_after: int | None = None
    # True when the assertion's left-hand subject was itself rewritten, not
    # just the matcher — that is a different edit from a style change.
    subject_changed: bool | None = None
    # Detector-set event kind. Optional; currently TEST_DISABLED only.
    shape: str | None = None

    def sort_key(self) -> tuple:
        from checkwash.gating import RULE_ORDER

        try:
            rank = RULE_ORDER.index(self.rule)
        except ValueError:
            rank = len(RULE_ORDER)
        return (rank, self.path, self.unit or "", self.rule, self.fingerprint)


def make_fingerprint(rule: str, path: str, qualname: str | None, before_text: str) -> str:
    digest = hashlib.sha256(
        "/".join([rule, path, qualname or "", normalize_text(before_text)]).encode("utf-8")
    ).hexdigest()[:12]
    return f"{rule}/{path}/{qualname or '-'}/{digest}"


def identity_text(text: str | None) -> str | None:
    """The v2 identities' normal form of an assertion's text, or None.

    `normalize_text`'s form with one difference: a JS template literal is
    kept as written, since it is the literal's value, and the code of each
    `${...}` in it is normalized as code. A v2-only scanner: `normalize_text`
    is unchanged, because pairing and move detection read it (#421 Q3).
    Never raises: text that cannot be read is None.
    """
    if text is None:
        return None
    try:
        out: list[str] = []
        _identity_code(text, 0, out, False)
        return "".join(out)
    except (RecursionError, MemoryError, TypeError):
        return None


def _identity_code(text: str, i: int, out: list[str], in_template: bool) -> int:
    """Code from `i`, normalized as `normalize_text` does; in a `${...}`, up to its closing brace."""
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch * 3 if text[i : i + 3] == ch * 3 else ch
            out.append(quote)
            i += len(quote)
            while i < n:
                if text[i] == "\\" and len(quote) == 1 and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                if text.startswith(quote, i):
                    out.append(quote)
                    i += len(quote)
                    break
                out.append(text[i])
                i += 1
        elif ch == "`":
            i = _identity_template(text, i, out)
        elif in_template and ch == "{":
            depth += 1
            out.append(ch)
            i += 1
        elif in_template and ch == "}":
            if depth == 0:
                return i
            depth -= 1
            out.append(ch)
            i += 1
        elif ch.isspace():
            i += 1
        else:
            out.append(ch)
            i += 1
    return i


def _identity_template(text: str, i: int, out: list[str]) -> int:
    """A template literal from its backtick at `i`: kept as written, each `${...}` read as code."""
    n = len(text)
    out.append("`")
    i += 1
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
        elif text[i] == "`":
            out.append("`")
            return i + 1
        elif text.startswith("${", i):
            out.append("${")
            i = _identity_code(text, i + 2, out, True)
            if i < n:
                out.append("}")
                i += 1
        else:
            out.append(text[i])
            i += 1
    return i


# (ordinal, count) of each of a side's assertions among those with the same
# text, for the last sides asked about: a unit that loses a thousand
# assertions asks a thousand times, and rebuilding it each time is quadratic.
# An entry holds its side, so neither the side's id nor its assertions' ids
# can be reused while it is cached.
_POSITIONS: dict[int, tuple] = {}


def _positions(side) -> dict[int, tuple[int, int]]:
    entry = _POSITIONS.get(id(side))
    if entry is not None and entry[0] is side and entry[1] == len(side.assertions):
        return entry[2]
    groups: dict[str | None, list] = {}
    for a in side.assertions:
        groups.setdefault(identity_text(a.text), []).append(a)
    positions = {id(a): (rank, len(group)) for group in groups.values() for rank, a in enumerate(group)}
    if len(_POSITIONS) >= 64:
        _POSITIONS.clear()
    _POSITIONS[id(side)] = (side, len(side.assertions), positions)
    return positions


def assertion_position(side, assertion) -> tuple[int | None, int | None]:
    """(ordinal, count) of `assertion` among its side's assertions that read the same, or (None, None).

    Two identical assertions in one unit are two approvals: the ordinal
    tells them apart, and the count catches one deleted in a later change
    (#421 Q3). The order is the side's own: the unit's own and same-file
    assertions in source order, the copies of one helper assertion in the
    order of their call sites, then those from other files. No span is part
    of an identity, so a line shift keeps the key.
    """
    try:
        if side is None or assertion is None or identity_text(assertion.text) is None:
            return None, None
        return _positions(side).get(id(assertion), (None, None))
    except (AttributeError, TypeError, RecursionError):
        return None, None


def assertion_identity(
    rule: str,
    path: str,
    qualname: str | None,
    legacy_text: str,
    *,
    before: str | None,
    after: str | None,
    kind: str,
    position: tuple[int | None, int | None] = (None, None),
    context=None,
) -> dict:
    """What a content-bound assertion-level key is computed from (#421 Q3).

    It holds the exact pre-image of the legacy key (`make_fingerprint`'s), so
    every v2 key refines its legacy key, plus the complete before and after
    texts, the event kind, the before side's ordinal and count of that text,
    and the rule's context. Spans, line numbers, messages, strengths,
    severities, file digests and revision labels stay out. TEST_DISABLED
    builds its keys with it too (#512): its texts are a marker's or a
    guard's, its kind is the finding's shape, and it records no position
    (`detectors/test_disabled.py`).
    """
    ordinal, count = position
    return {
        "scheme": "checkwash/assertion-fingerprint/v2",
        "rule": rule,
        "path": path,
        "unit": qualname,
        "legacy": "/".join([rule, path, qualname or "", normalize_text(legacy_text)]),
        "before": identity_text(before),
        "after": identity_text(after),
        "kind": kind,
        "ordinal": ordinal,
        "count": count,
        "context": context,
    }


def canonical(value):
    """`value` as JSON-native data whose encoding does not depend on the process.

    A set or frozenset (`ast.literal_eval` makes them from literal arguments
    and table cells) becomes a list sorted by its members' encodings: its own
    iteration order, and so `str()` of it, follows the hash seed. Tuples
    become lists; another value JSON has no form for (bytes, complex,
    Ellipsis) becomes its `repr`.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        # A key that is not text (a literal `{1: "a"}` or `{(1, 2): "a"}`)
        # becomes its JSON encoding, as json.dumps writes an int key.
        return {(k if isinstance(k, str) else json.dumps(canonical(k), sort_keys=True, ensure_ascii=True)):
                canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        members = [canonical(v) for v in value]
        return sorted(members, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=True, default=repr))
    return repr(value)


def assertion_key(identity: dict) -> str:
    """`rule/path/unit/v2:<64hex>`: the full SHA256 of an identity's canonical JSON.

    It never raises: a context it cannot encode is recorded as null.
    """
    try:
        encoded = json.dumps(canonical(identity), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        identity = {**identity, "context": None}
        encoded = json.dumps(canonical(identity), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return f"{identity['rule']}/{identity['path']}/{identity['unit'] or '-'}/v2:{digest}"


def make_assertion_fingerprint(rule: str, path: str, qualname: str | None, legacy_text: str, **evidence) -> str:
    """The content-bound key of an assertion-level or TEST_DISABLED finding (#421, #512): `assertion_identity`, hashed."""
    return assertion_key(assertion_identity(rule, path, qualname, legacy_text, **evidence))


def change_identity(file: FileIR) -> dict:
    """Validated content pair, also usable for a finding's companion files."""
    evidence = file.change_evidence
    if evidence is None:
        raise EngineError(f"{file.path}: missing content-bound fingerprint evidence")
    expected_sides = {"added": (False, True), "modified": (True, True), "deleted": (True, False)}
    sides = (evidence.before_sha256, evidence.after_sha256)
    if file.status not in expected_sides or any(
        (not isinstance(digest, str) or not _CONTENT_DIGEST.fullmatch(digest))
        if required else digest is not None
        for digest, required in zip(sides, expected_sides.get(file.status, ()))
    ):
        raise EngineError(f"{file.path}: invalid content-bound fingerprint evidence for {file.status!r}")
    return {
        "path": file.path,
        "role": file.role,
        "status": file.status,
        "old_path": evidence.old_path,
        "rename_to": evidence.rename_to,
        "before_sha256": evidence.before_sha256,
        "after_sha256": evidence.after_sha256,
    }


def make_change_fingerprint(rule: str, file: FileIR, context: dict) -> str:
    """Bind an exemption to both snapshots and the detector's event context.

    Full SHA256 and canonical JSON avoid truncated identities and ambiguous
    slash-joined evidence. No before-only, path-only or legacy-key fallback.
    """
    stored_expectation = rule == "EXPECTED_VALUE_CHANGED" and file.role == "snapshot"
    if rule not in CHANGE_FINGERPRINT_RULES and not stored_expectation:
        raise EngineError(f"{rule}/{file.path}: unsupported content-bound fingerprint rule")
    payload = {
        "scheme": "checkwash/change-fingerprint/v2",
        "rule": rule,
        **change_identity(file),
        "context": context,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return f"{rule}/{file.path}/-/v2:{digest}"
