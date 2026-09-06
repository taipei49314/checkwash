"""Issue 131: retain wrapper evidence and require closed equivalence proof."""

import datetime
import json

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import EngineError, FileChange, analyze, run_detectors
from checkwash.ir.model import Assertion, AssertionPair, DiffGlobals, FileIR, IR, Unit, UnitDelta, UnitSide, to_jsonable


BEFORE = b'from app.parse_bool import parse_bool\n\ndef test_yes():\n    assert parse_bool("Yes") is True\n'
AFTER = b'from app.parse_bool import parse_bool\n\ndef normalize_input(s):\n    return s.strip().lower()\n\ndef test_yes():\n    assert parse_bool(normalize_input("Yes")) is True\n'
PRODUCTION = b'def parse_bool(s):\n    return s.strip().lower() in {"1", "true", "yes"}\n'
SNAPSHOT = {"src/app/parse_bool.py": PRODUCTION}


def run(before=BEFORE, after=AFTER, *, snapshot=SNAPSHOT, extra=(), strict=True):
    return analyze(
        [FileChange("tests/test_bool.py", "modified", before, after), *extra],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
        root_reader=snapshot.get if strict else None, head_reader=snapshot.get,
        root_searcher=(lambda needles: [p for p, data in sorted(snapshot.items()) if data]) if strict else None,
    )


@pytest.mark.parametrize("expression", [
    'normalize_input("Yes")', '"Yes".strip().lower()', '"Yes".lower()',
    '"Yes".upper().lower()',
])
def test_literal_string_normalization_redundant_with_pure_production(expression):
    after = AFTER.replace(b'normalize_input("Yes")', expression.encode())
    ir, findings, verdict = run(after=after)
    assert verdict == "pass"
    assert findings == []
    assert ir.files[0].normalization_equivalent_pairs == (("test_yes", "a0", "a0"),)


def test_the_honest_rewrite_still_rejects_a_wrong_production_result():
    # Execute only this fixed regression example, never an analyzed repository.
    def honest(s):
        return s.strip().lower() in {"1", "true", "yes"}

    def broken(s):
        return s.strip().lower() in {"0", "false", "no"}

    normalize_input = lambda s: s.strip().lower()
    assert honest("Yes") is True
    assert honest(normalize_input("Yes")) is True
    assert broken("Yes") is False
    assert broken(normalize_input("Yes")) is False


def test_all_three_literal_callers_in_the_report_keep_their_oracles():
    before = BEFORE + b'\ndef test_true_upper():\n    assert parse_bool("TRUE") is True\n\ndef test_no():\n    assert parse_bool("no") is False\n'
    after = AFTER + b'\ndef test_true_upper():\n    assert parse_bool(normalize_input("TRUE")) is True\n\ndef test_no():\n    assert parse_bool(normalize_input("no")) is False\n'
    ir, findings, verdict = run(before, after)
    assert verdict == "pass"
    assert findings == []
    assert len(ir.files[0].normalization_equivalent_pairs) == 3


@pytest.mark.parametrize("production", [
    b'def parse_bool(s):\n    return s in {"1", "true", "yes"}\n',
    b'def parse_bool(s):\n    return s.strip() in {"1", "true", "yes"}\n',
    b'def parse_bool(s):\n    if False:\n        return s.strip().lower()\n    return s in {"1", "true", "yes"}\n',
    b'def parse_bool(s):\n    ignored = s.strip().lower()\n    return s in {"1", "true", "yes"}\n',
    b'def parse_bool(s):\n    mutate()\n    return s.strip().lower() in {"1", "true", "yes"}\n',
    b'def parse_bool(s=disable()):\n    return s.strip().lower() in {"1", "true", "yes"}\n',
    b'@decorate\ndef parse_bool(s):\n    return s.strip().lower() in {"1", "true", "yes"}\n',
    b'def parse_bool(s: disable()):\n    return s.strip().lower() in {"1", "true", "yes"}\n',
    PRODUCTION + b'\nparse_bool = lambda s: False\n',
    PRODUCTION + b'\nparse_bool.__code__ = evil.__code__\n',
])
def test_same_method_names_or_unsafe_production_body_do_not_grant_credit(production):
    ir, findings, verdict = run(snapshot={"src/app/parse_bool.py": production})
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("SUBJECT_NORMALIZED", "high")]
    assert ir.files[0].normalization_equivalent_pairs == ()


@pytest.mark.parametrize("after", [
    AFTER.replace(b"def normalize_input(s):", b"def normalize_input(s=disable()):"),
    AFTER.replace(b"def normalize_input(s):", b"@decorate\ndef normalize_input(s):"),
    AFTER.replace(b"def normalize_input(s):", b"def normalize_input(s: disable()):"),
    AFTER.replace(b"    return s.strip().lower()", b"    mutate()\n    return s.strip().lower()"),
    AFTER.replace(b"    return s.strip().lower()", b"    return s.strip().lower() if safe else s"),
    AFTER.replace(b"    assert parse_bool", b"    parse_bool = evil\n    assert parse_bool"),
    AFTER.replace(b"def test_yes():", b"def test_yes(parse_bool):"),
    AFTER.replace(b"def test_yes():", b"@patch\ndef test_yes():"),
    AFTER + b"\nnormalize_input = evil\n",
    AFTER + b"\nif True:\n    parse_bool = evil\n",
    AFTER + b"\nnormalize_input.__code__ = evil.__code__\n",
    AFTER.replace(b"    assert parse_bool", b"    mutate()\n    assert parse_bool"),
    AFTER + b"\ndef test_mutator():\n    assert disable() == None\n",
    AFTER + b'\ndef test_mutator():\n    assert parse_bool(disable()) is True\n',
])
def test_test_side_bindings_defaults_or_other_effects_do_not_grant_credit(after):
    ir, findings, verdict = run(after=after)
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" and f.severity == "high" for f in findings)
    assert ir.files[0].normalization_equivalent_pairs == ()


@pytest.mark.parametrize("path,source", [
    ("app/parse_bool.py", PRODUCTION),
    ("tests/app/parse_bool.py", PRODUCTION),
    ("src/app/parse_bool/__init__.py", PRODUCTION),
    ("app.py", b"# shadows the src package\n"),
    ("src/app/__init__.py", b"from . import mutate\n"),
    ("tests/app/__init__.py", b"def __getattr__(name):\n    return evil\n"),
])
def test_ambiguous_or_executable_package_bindings_do_not_grant_credit(path, source):
    ir, findings, verdict = run(snapshot={**SNAPSHOT, path: source})
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)
    assert ir.files[0].normalization_equivalent_pairs == ()


def test_empty_package_initializers_are_supported():
    _, findings, verdict = run(snapshot={**SNAPSHOT, "src/app/__init__.py": b'"""Package docs."""\n'})
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("snapshot,strict", [({}, True), (SNAPSHOT, False)])
def test_missing_or_legacy_snapshot_callback_cannot_prove_equivalence(snapshot, strict):
    _, findings, verdict = run(snapshot=snapshot, strict=strict)
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)


def test_snapshot_read_error_remains_an_engine_error():
    def unavailable(path):
        raise EngineError("snapshot unavailable")

    with pytest.raises(EngineError, match="snapshot unavailable"):
        analyze([FileChange("tests/test_bool.py", "modified", BEFORE, AFTER)],
                Config(), Contract(), [], datetime.date(2026, 9, 6), root_reader=unavailable,
                root_searcher=lambda needles: [])


def test_other_changed_file_cannot_borrow_the_closed_caller_proof():
    ir, _, _ = run(extra=[FileChange("other.py", "added", None, b"patch_target()\n")])
    assert ir.files[-1].normalization_equivalent_pairs == ()


@pytest.mark.parametrize("production", [
    b'def parse_bool(s):\n    return s.strip().lower() is "yes"\n',
    b'def parse_bool(s):\n    return s.strip().lower() is not "yes"\n',
])
def test_string_identity_is_not_proved_from_equal_string_values(production):
    _, findings, verdict = run(snapshot={"src/app/parse_bool.py": production})
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)


def test_unicode_normalization_does_not_depend_on_the_hosts_unicode_version():
    before = BEFORE.replace(b'"Yes"', '"\u1e9e"'.encode())
    after = AFTER.replace(b'"Yes"', '"\u1e9e"'.encode())
    _, findings, verdict = run(before, after)
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)


@pytest.mark.parametrize("wrapper", ["abs(result)", "sorted(result)", "set(result)", "result.lower()"])
def test_wrapped_bound_result_retains_its_direct_subject_evidence(wrapper):
    before = b"def test_result():\n    result = calculate()\n    assert result == expected\n"
    after = before.replace(b"assert result", f"assert {wrapper}".encode())
    _, findings, verdict = run(before, after)
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("before,after", [
    ('is_anagram("Listen", "Silent")', 'is_anagram("Listen".lower(), "Silent".lower())'),
    ('calculate(2)', 'abs(calculate(2))'),
    ('normalize(" Ab ")', 'expected_value(normalize(" Ab "))'),
])
def test_ordinary_assert_inline_and_result_wrappers_remain_detected(before, after):
    old = f"def test_result():\n    assert {before} == expected\n".encode()
    new = f"def test_result():\n    assert {after} == expected\n".encode()
    _, findings, verdict = run(old, new)
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)


def test_plain_binding_hoist_is_not_normalization():
    before = b"def test_result():\n    assert calculate() == expected\n"
    after = b"def test_result():\n    result = calculate()\n    assert result == expected\n"
    _, findings, verdict = run(before, after)
    assert verdict == "pass"
    assert findings == []


def test_json_array_proof_records_preserve_findings_after_dataclass_reconstruction():
    original, original_findings, _ = run()
    payload = json.loads(json.dumps(to_jsonable(original)))
    files = []
    for data in payload.pop("files"):
        units = []
        for unit in data.pop("units"):
            for side in ("before", "after"):
                if unit[side] is not None:
                    side_data = unit[side]
                    side_data["assertions"] = [Assertion(**a) for a in side_data["assertions"]]
                    unit[side] = UnitSide(**side_data)
            if unit["delta"] is not None:
                delta = unit["delta"]
                delta["assertion_pairs"] = [AssertionPair(**p) for p in delta["assertion_pairs"]]
                unit["delta"] = UnitDelta(**delta)
            units.append(Unit(**unit))
        files.append(FileIR(**data, units=units))
    payload["globals"] = DiffGlobals(**payload["globals"])
    restored = IR(**payload, files=files)
    assert restored.files[0].normalization_equivalent_pairs == [["test_yes", "a0", "a0"]]
    assert run_detectors(restored, Config()) == original_findings == []


@pytest.mark.parametrize("records", [None, [None], ["test_yes", "a0", "a0"], [["test_yes", "a0"]]])
def test_malformed_optional_proof_record_does_not_hide_the_finding(records):
    ir, _, _ = run()
    ir.files[0].normalization_equivalent_pairs = records
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in run_detectors(ir, Config()))
