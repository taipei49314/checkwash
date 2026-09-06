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
    )
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
        key_rule in CHANGE_FINGERPRINT_RULES | {"EXPECTED_VALUE_CHANGED"}
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
