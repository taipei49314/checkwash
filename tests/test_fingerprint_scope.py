"""An exemption identifies reviewed content, not every edit of one path."""

import datetime
import json
from dataclasses import replace

import pytest

from checkwash import FINDINGS_VERSION, IR_VERSION
from checkwash.allowlist import (
    AllowEntry,
    active_fingerprints,
    fingerprint_diagnostics,
    load_allowlist,
    summarize_allowlist,
)
from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.globals_rules import detect_ci_touched, detect_guardrail, detect_unparseable_test
from checkwash.engine import _classify_allowlist_change, analyze
from checkwash.findings import fingerprint_issue, make_change_fingerprint, make_fingerprint
from checkwash.ir.model import ChangeEvidence, IR, to_jsonable

TODAY = datetime.date(2026, 9, 6)
PATH = "AGENTS.md"
BEFORE = b"# Policy\nRun tests.\n"
AFTER = b"# Policy\nRun tests and lint.\n"


def _analyze(before=BEFORE, after=AFTER, *, path=PATH, status="modified", old_path=None):
    return analyze(
        [FileChange(path, status, before, after, old_path=old_path)],
        Config(), Contract(), [], TODAY,
    )


def _fingerprint(before=BEFORE, after=AFTER, **kwargs):
    _ir, findings, _verdict = _analyze(before, after, **kwargs)
    return next(f.fingerprint for f in findings if f.rule == "GUARDRAIL_TOUCHED")


def _entry(fingerprint, **kwargs):
    entry = AllowEntry(
        fingerprint, fingerprint.split("/", 1)[0], "reviewed exact diff", "reviewer",
        "2026-09-02", "2026-12-01",
    )
    return replace(entry, **kwargs)


def _ledger(*entries):
    return "\n".join(
        "[[allow]]\n" + "\n".join(f"{key} = {json.dumps(value)}" for key, value in vars(e).items())
        for e in entries
    ).encode("utf-8")


def test_both_snapshots_and_exact_whitespace_are_part_of_identity():
    baseline = _fingerprint()
    assert baseline.startswith("GUARDRAIL_TOUCHED/AGENTS.md/-/v2:")
    assert len(baseline.rsplit(":", 1)[1]) == 64
    assert _fingerprint(after=b"# Policy\nDo not run tests.\n") != baseline
    assert _fingerprint(before=b"# Policy\nRun integration tests.\n") != baseline
    assert _fingerprint(after=AFTER.replace(b"Run tests", b"Run  tests")) != baseline
    assert _fingerprint(after=AFTER.replace(b"Run tests", b"  Run tests")) != baseline
    assert _fingerprint(after=AFTER + "測試🙂\n".encode()) != baseline
    assert _fingerprint(after=AFTER + b"\xff") != _fingerprint(after=AFTER + b"\xfe")


def test_only_crlf_is_canonicalized_and_ir_contains_digests_not_new_source_copies():
    assert _fingerprint(BEFORE.replace(b"\n", b"\r\n"), AFTER.replace(b"\n", b"\r\n")) == _fingerprint()
    ir, _findings, _verdict = _analyze()
    record = to_jsonable(ir.files[0].change_evidence)
    assert set(record) == {"before_sha256", "after_sha256", "old_path", "rename_to"}
    assert all(len(record[key]) == 64 for key in ("before_sha256", "after_sha256"))
    assert "Run tests" not in json.dumps(record)
    assert IR_VERSION == FINDINGS_VERSION == ir.version == 2


def test_absent_and_empty_sides_are_not_interchangeable():
    assert _fingerprint(None, b"", status="added") != _fingerprint(b"", None, status="deleted")
    assert _fingerprint(None, AFTER, status="added") != _fingerprint(b"", AFTER)
    assert _fingerprint(BEFORE, None, status="deleted") != _fingerprint(BEFORE, b"")


def test_path_and_rename_destination_are_part_of_identity():
    assert _fingerprint(path="CLAUDE.md") != _fingerprint()
    assert _fingerprint(path="CLAUDE.md", old_path="AGENTS.md") != _fingerprint(path="CLAUDE.md")
    first = _fingerprint(path="docs/old-policy.md", old_path="AGENTS.md")
    second = _fingerprint(path="docs/another-policy.md", old_path="AGENTS.md")
    assert first != second
    assert first != _fingerprint(BEFORE, None, status="deleted")
    assert _fingerprint(path=".claude/policy.md") == _fingerprint(path=r".claude\policy.md")


@pytest.mark.parametrize("rule,detector,global_field", [
    ("GUARDRAIL_TOUCHED", detect_guardrail, "guardrail_files_changed"),
    ("CI_WORKFLOW_TOUCHED", detect_ci_touched, "ci_files_changed"),
])
def test_missing_ir_evidence_never_falls_back_to_path_identity(rule, detector, global_field):
    ir = IR("base", "head")
    setattr(ir.globals, global_field, [PATH])
    with pytest.raises(EngineError, match="missing.*evidence"):
        detector(ir)
    ir, _findings, _verdict = _analyze()
    ir.files[0].change_evidence = None
    if rule == "CI_WORKFLOW_TOUCHED":
        ir.globals.guardrail_files_changed = []
        ir.globals.ci_files_changed = [PATH]
    with pytest.raises(EngineError, match="missing.*evidence"):
        detector(ir)


def test_all_ci_event_context_is_bound_independently_of_message_wording():
    ir, _findings, _verdict = _analyze(
        b"jobs:\n  test:\n    steps:\n      - run: pytest\n",
        b"jobs:\n  test:\n    steps:\n      - run: pytest || true\n",
        path=".github/workflows/test.yml",
    )
    first = detect_ci_touched(ir)[0]
    ir.globals.ci_weakening_lines.append((first.path, "second distinct weakening"))
    second = detect_ci_touched(ir)[0]
    assert first.message == second.message  # the human report shows the first line only
    assert first.fingerprint != second.fingerprint
    ir.globals.ci_weakening_lines.reverse()
    assert detect_ci_touched(ir)[0].fingerprint == second.fingerprint


@pytest.mark.parametrize("status,before,after", [
    ("modified", None, None), ("modified", None, "a" * 64),
    ("modified", "b" * 64, None), ("modified", "a" * 63, "b" * 64),
    ("modified", "a" * 64, "g" * 64), ("modified", "A" * 64, "b" * 64),
    ("modified", 123, "b" * 64), ("added", "a" * 64, "b" * 64),
    ("added", None, None), ("deleted", "a" * 64, "b" * 64),
    ("deleted", None, None), ("renamed", "a" * 64, "b" * 64),
])
def test_invalid_content_evidence_fails_closed(status, before, after):
    ir, _findings, _verdict = _analyze()
    file = replace(ir.files[0], status=status, change_evidence=ChangeEvidence(before, after))
    with pytest.raises(EngineError, match="invalid.*evidence"):
        make_change_fingerprint("GUARDRAIL_TOUCHED", file, {})


def test_guardrail_creation_context_is_bound():
    ir, findings, _verdict = _analyze(None, AFTER, status="added")
    first = next(f for f in findings if f.rule == "GUARDRAIL_TOUCHED")
    ir.globals.guardrail_configs_created_loosening.append(PATH)
    assert detect_guardrail(ir)[0].fingerprint != first.fingerprint


def test_new_keys_do_not_depend_on_revision_labels_or_other_files():
    ir, findings, _verdict = analyze(
        [FileChange(PATH, "modified", BEFORE, AFTER), FileChange("notes.md", "added", None, b"note\n")],
        Config(), Contract(), [], TODAY, base_label="another-base", head_label="another-head",
    )
    assert next(f.fingerprint for f in findings if f.rule == "GUARDRAIL_TOUCHED") == _fingerprint()
    assert detect_guardrail(ir)[0].fingerprint == _fingerprint()


@pytest.mark.parametrize("rule,path", [
    ("GUARDRAIL_TOUCHED", PATH), ("CI_WORKFLOW_TOUCHED", ".github/workflows/test.yml"),
])
@pytest.mark.parametrize("declared_rule", [None, "ASSERT_REMOVED", ""])
def test_retired_keys_are_kept_by_parser_but_never_eligible(rule, path, declared_rule):
    key = make_fingerprint(rule, path, None, path)
    entry = _entry(key, rule=rule if declared_rule is None else declared_rule)
    data = _ledger(entry)
    parsed, error = load_allowlist(data)
    assert error is None and parsed == [entry]
    assert active_fingerprints(parsed, TODAY) == set()
    summary = summarize_allowlist(data, TODAY)
    assert summary.active == 0 and summary.retired == 1
    assert key in fingerprint_diagnostics(parsed)[0]
    assert "retired" in fingerprint_diagnostics(parsed)[0]


def test_v2_rule_spoofing_and_malformed_new_keys_are_rejected():
    key = _fingerprint()
    assert fingerprint_issue(key) is None
    assert active_fingerprints([_entry(key, rule="ASSERT_REMOVED")], TODAY) == set()
    assert "does not match" in fingerprint_issue(key, "ASSERT_REMOVED")
    assert fingerprint_issue(key[:-1]) is not None
    assert fingerprint_issue(key + "a") is not None
    assert fingerprint_issue(key.upper()) is not None


def test_unmigrated_namespace_keeps_existing_metadata_compatibility():
    key = make_fingerprint("ASSERT_REMOVED", "tests/test_x.py", "test_x", "assert actual == 5")
    entry = _entry(key, rule="GUARDRAIL_TOUCHED")
    assert fingerprint_issue(key, entry.rule) is None
    assert active_fingerprints([entry], TODAY) == {key}


def test_mixed_ledger_has_shared_expiry_retirement_and_invalid_counts():
    key = _fingerprint()
    legacy = make_fingerprint("GUARDRAIL_TOUCHED", PATH, None, PATH)
    unchanged = make_fingerprint("ASSERT_REMOVED", "tests/test_x.py", "test_x", "assert actual == 5")
    entries = [
        _entry(key), _entry(unchanged), _entry(legacy),
        _entry(key, rule="ASSERT_REMOVED"),
        _entry(key, expires="2026-09-05"),
        _entry(key, expires="2028-01-01"),
    ]
    data = b"\xef\xbb\xbf" + _ledger(*entries)
    parsed, error = load_allowlist(data)
    assert error is None and parsed == entries
    summary = summarize_allowlist(data, TODAY)
    assert (summary.active, summary.retired, summary.invalid, summary.expired, summary.over_cap) == (2, 1, 1, 1, 1)
    assert active_fingerprints(parsed, TODAY) == {key, unchanged}


def test_retirement_does_not_hide_existing_ledger_edits():
    retired = _entry(make_fingerprint("GUARDRAIL_TOUCHED", PATH, None, PATH))
    before = _ledger(retired)
    assert _classify_allowlist_change(before, b"") is None
    assert _classify_allowlist_change(before, _ledger(replace(retired, reason="different"))) is None
    new = _entry(_fingerprint())
    assert _classify_allowlist_change(before, _ledger(retired, new)) == [new.fingerprint]


def test_sarif_versions_only_the_changed_identity_scheme():
    from checkwash.findings import Finding
    from checkwash.report.sarif import findings_to_sarif

    ir, findings, _ = _analyze()
    unchanged = make_fingerprint("ASSERT_REMOVED", "test_x.py", "test_x", "assert x")
    findings.append(Finding("ASSERT_REMOVED", "high", "removed", "test_x.py", "test_x", fingerprint=unchanged))
    results = json.loads(findings_to_sarif(ir, findings))["runs"][0]["results"]
    keys = {result["ruleId"]: result["partialFingerprints"] for result in results}
    assert keys["GUARDRAIL_TOUCHED"] == {"checkwash/v2": _fingerprint()}
    assert keys["ASSERT_REMOVED"] == {"checkwash/v1": unchanged}


def test_unparseable_identity_binds_content_pair_and_parser_state():
    path = "tests/test_api.py"
    before, after = b"VALUE = 5\nassert VALUE == 5\n", b"VALUE = (\nassert VALUE == 5\n"
    ir, findings, _ = _analyze(before, after, path=path)
    hit = next(f for f in findings if f.rule == "TEST_FILE_UNPARSEABLE")
    assert hit.severity == "high" and hit.fingerprint.startswith(f"TEST_FILE_UNPARSEABLE/{path}/-/v2:")
    ir.globals.unparseable_tests = [(path, False)]
    assert detect_unparseable_test(ir)[0].fingerprint != hit.fingerprint
    for changed_before, changed_after in [(before + b"# earlier\n", after), (before, after + b"# later\n")]:
        _, changed, _ = _analyze(changed_before, changed_after, path=path)
        assert next(f for f in changed if f.rule == hit.rule).fingerprint != hit.fingerprint
    ir.files.clear()
    with pytest.raises(EngineError, match="missing.*evidence"):
        detect_unparseable_test(ir)
