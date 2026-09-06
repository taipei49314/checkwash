"""Additive concrete table wrappers must not create precision credit."""

import datetime
import json
import os
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.subject_normalized import detect
from checkwash.engine import FileChange, analyze
from checkwash.ir.model import DiffGlobals, FileIR, IR, to_jsonable


PATH = "tests/test_subject.py"
ABS_BEFORE = b'''from app.absint import abs_int
def test_abs_int():
    assert abs_int(5) == 5
    assert abs_int(-3) == 3
    assert abs_int(0) == 0
'''
ABS_AFTER = b'''from app.absint import abs_int
import pytest
@pytest.mark.parametrize("n, expected", [(5, 5), (-3, 3), (0, 0)])
def test_abs_int(n, expected):
    result = abs_int(n)
    assert abs(result) == expected
'''
PAL_BEFORE = b'''from app.palindrome import is_palindrome
def assert_pal(text, expected):
    assert is_palindrome(text) is expected
def test_mixed_case():
    assert_pal("Aba", True)
def test_phrase():
    assert_pal("Never odd or even", True)
def test_negative():
    assert_pal("xyz", False)
'''
PAL_AFTER = b'''from app.palindrome import is_palindrome
import pytest
@pytest.mark.parametrize("text, expected", [("Aba", True), ("Never odd or even", True), ("xyz", False)])
def test_palindrome(text, expected):
    folded = "".join(ch for ch in text if ch.isalnum()).lower()
    assert is_palindrome(folded) is expected
'''


def run(before=ABS_BEFORE, after=ABS_AFTER, *, snapshot=None, strict=True, extra=()):
    snapshot = {**(snapshot or {}), PATH: after}
    return analyze([FileChange(PATH, "modified", before, after), *extra], Config(), Contract(), [],
                   datetime.date(2026, 9, 6), root_reader=snapshot.get if strict else None,
                   root_searcher=(lambda _: [p for p in sorted(snapshot) if p.endswith(".py")]) if strict else None)


@pytest.mark.parametrize("before,after", [(ABS_BEFORE, ABS_AFTER), (PAL_BEFORE, PAL_AFTER)])
def test_named_table_wrappers_add_high_findings_without_projecting_units(before, after):
    ir, findings, verdict = run(before, after)
    assert verdict == "block"
    wrappers = [f for f in findings if f.rule == "SUBJECT_NORMALIZED"]
    assert len(wrappers) == 3
    assert all(f.severity == "high" for f in wrappers)
    assert len({f.fingerprint for f in wrappers}) == 3
    assert not any(u.qualname.startswith("test_concrete_") for file in ir.files for u in file.units)
    assert not any(file.normalization_equivalent_pairs for file in ir.files)


@pytest.mark.parametrize("before,after", [
    (ABS_BEFORE, ABS_AFTER.replace(b"abs(result)", b"result")),
    (PAL_BEFORE, PAL_AFTER.replace(b'is_palindrome(folded)', b'is_palindrome(text)')),
    (ABS_BEFORE, ABS_AFTER.replace(b"(5, 5), (-3, 3), (0, 0)", b"(5, 15), (-3, 13), (0, 10)")),
    (ABS_BEFORE, ABS_AFTER.replace(b"(5, 5), (-3, 3), (0, 0)", b"(6, 5), (-4, 3), (1, 0)")),
    (ABS_BEFORE, ABS_AFTER.replace(b"absint import abs_int", b"absint import wrong as abs_int")),
    (ABS_BEFORE, ABS_AFTER.replace(b"    result =", b"    abs = lambda x: x\n    result =")),
    (ABS_BEFORE, ABS_AFTER.replace(b"    assert abs", b"    result = 3\n    assert abs")),
    (ABS_BEFORE, ABS_AFTER.replace(b"    assert abs", b"    if False:\n        assert abs")),
    (PAL_BEFORE, PAL_AFTER.replace(b"ch.isalnum()", b"predicate(ch)")),
    (PAL_BEFORE, PAL_AFTER.replace(b"ch for ch in text", b"text for text in text")),
    (PAL_BEFORE.replace(b"assert_pal(text, expected)", b"assert_pal(text, expected=mutate())"), PAL_AFTER),
    (ABS_BEFORE, ABS_AFTER.replace(b'"n, expected", [(5, 5), (-3, 3), (0, 0)]', b'"n, expected", load_rows()')),
])
def test_unrelated_or_opaque_rows_do_not_get_table_normalization_evidence(before, after):
    ir, _findings, _verdict = run(before, after)
    assert not any(file.table_normalization_events for file in ir.files)


def test_reversed_table_to_plain_rewrite_adds_no_wrapper_event():
    ir, _, _ = run(ABS_AFTER, ABS_BEFORE)
    assert not any(file.table_normalization_events for file in ir.files)


def test_added_wrapped_table_does_not_replace_preserved_raw_oracles():
    raw = ABS_AFTER.replace(b"abs(result)", b"result")
    extra = ABS_AFTER.split(b"@pytest.mark.parametrize", 1)[1].replace(
        b"def test_abs_int", b"def test_abs_extra")
    ir, _, _ = run(after=raw + b"\n@pytest.mark.parametrize" + extra)
    assert not any(file.table_normalization_events for file in ir.files)


def test_repeated_table_binding_does_not_erase_mutable_aliases():
    before = ABS_BEFORE.replace(b"abs_int(5)", b"abs_int([5], [5])").replace(
        b"abs_int(-3)", b"abs_int([-3], [-3])").replace(b"abs_int(0)", b"abs_int([0], [0])")
    after = ABS_AFTER.replace(b"abs_int(n)", b"abs_int(n, n)").replace(
        b"[(5, 5), (-3, 3), (0, 0)]", b"[([5], 5), ([-3], 3), ([0], 0)]")
    assert not run(before, after)[0].files[0].table_normalization_events


@pytest.mark.parametrize("path", ["pytest.py", "src/pytest.py", "tests/conftest.py", "tests/__init__.py"])
def test_ambiguous_decorator_or_runtime_context_withholds_events(path):
    ir, _, _ = run(snapshot={path: b"replace_subject()\n"})
    assert not any(file.table_normalization_events for file in ir.files)


def test_unknown_snapshot_or_another_changed_file_withholds_events():
    assert not run(strict=False)[0].files[0].table_normalization_events
    extra = [FileChange("app/absint.py", "modified", b"old = 1\n", b"old = 2\n")]
    assert not run(extra=extra)[0].files[0].table_normalization_events


def test_json_native_events_keep_source_spans_fingerprints_and_deduplication():
    before = "# 原始 oracle\r\n".encode() + PAL_BEFORE.replace(b"\n", b"\r\n")
    after = "# 參數表\r\n".encode() + PAL_AFTER.replace(b"\n", b"\r\n")
    ir, _, _ = run(before, after)
    original = [f for f in detect(ir) if "literal parameter row" in f.message]
    raw = json.loads(json.dumps(to_jsonable(ir)))
    file = FileIR(path=PATH, language="python", role="test", status="modified",
                  table_normalization_events=raw["files"][0]["table_normalization_events"])
    rebuilt = IR(base="before", head="after", files=[file], globals=DiffGlobals())
    result = detect(rebuilt)
    assert [f.fingerprint for f in result] == [f.fingerprint for f in original]
    for finding in result:
        assert before.decode().replace("\r\n", "\n")[slice(*finding.before.span)] == finding.before.text
        assert after.decode().replace("\r\n", "\n")[slice(*finding.after.span)] == finding.after.text
    file.table_normalization_events *= 2
    assert len(detect(rebuilt)) == len(result)


def test_line_shifts_keep_keys_and_report_actual_updated_source_location():
    from checkwash.findings import Evidence
    from checkwash.report.context import ReportContext

    original = [f for f in detect(run()[0]) if "literal parameter row" in f.message]
    prefix = b"# An explanatory comment\n\n"
    before, after = prefix + ABS_BEFORE, prefix + ABS_AFTER
    context = ReportContext()
    snapshot = {PATH: after}
    ir, _, _ = analyze([FileChange(PATH, "modified", before, after)], Config(), Contract(), [],
                       datetime.date(2026, 9, 6), root_reader=snapshot.get,
                       root_searcher=lambda _: [PATH], report_context=context)
    moved = [f for f in detect(ir) if "literal parameter row" in f.message]
    assert [f.fingerprint for f in moved] == [f.fingerprint for f in original]
    assert moved[0].after.span[0] == original[0].after.span[0] + len(prefix)
    assert context.location(PATH, Evidence(moved[0].after.text, moved[0].after.span)) == (PATH, 8)


def test_helper_fixed_expected_value_remains_part_of_fingerprint_identity():
    keys = []
    for value in (b"3", b"4"):
        before = b'''from app.absint import abs_int
def assert_abs(n):
    assert abs_int(n) == ''' + value + b'''
def test_negative():
    assert_abs(-3)
'''
        after = ABS_AFTER.replace(b"[(5, 5), (-3, 3), (0, 0)]", b"[(-3, " + value + b")]")
        findings = [f for f in detect(run(before, after)[0]) if "literal parameter row" in f.message]
        assert len(findings) == 1
        keys.append(findings[0].fingerprint)
    assert keys[0] != keys[1]


@pytest.mark.parametrize("events", [None, {}, [()], [["unit"] * 9],
    [["unit", "before", [-1, 2], "after", [1, 2], "f()", "abs(f())", "Eq", "3"]],
    [["unit", "before", [True, 2], "after", [1, 2], "f()", "abs(f())", "Eq", "3"]],
    [["unit", "before", [2, 2], "after", [1, 2], "f()", "abs(f())", "Eq", "3"]],
])
def test_malformed_record_cannot_silently_drop_additive_evidence(events):
    file = FileIR(path=PATH, language="python", role="test", status="modified", table_normalization_events=events)
    with pytest.raises(EngineError, match="literal-table normalization evidence"):
        detect(IR(base="before", head="after", files=[file], globals=DiffGlobals()))


@pytest.mark.parametrize("before,after,module,production", [
    (ABS_BEFORE, ABS_AFTER, "absint", b"def abs_int(n):\n    return n\n"),
    (PAL_BEFORE, PAL_AFTER, "palindrome", b"def is_palindrome(text):\n    return text == text[::-1]\n"),
])
def test_actual_pytest_bug_is_hidden_by_table_wrapper_and_checkwash_blocks(tmp_path, before, after, module, production):
    outcomes = []
    for side, source in (("before", before), ("after", after)):
        checkout = tmp_path / side
        (checkout / "app").mkdir(parents=True)
        (checkout / "tests").mkdir()
        (checkout / "app/__init__.py").write_bytes(b"")
        (checkout / f"app/{module}.py").write_bytes(production)
        (checkout / PATH).write_bytes(source)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", PATH], cwd=checkout,
                                capture_output=True, text=True, timeout=30,
                                env={**os.environ, "PYTHONPATH": str(checkout), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        outcomes.append(result.returncode)
    assert outcomes == [1, 0]
    assert run(before, after)[2] == "block"
