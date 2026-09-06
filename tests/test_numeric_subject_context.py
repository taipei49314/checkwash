"""A stronger comparison cannot pardon replacement of its data inputs."""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.expected_changed import detect
from checkwash.engine import _native_assertion_context, analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.model import FileIR


def _run(before, after):
    return analyze(
        [FileChange("tests/test_value.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
    )


@pytest.mark.parametrize("before,after", [
    ("def test_value(value=-5):\n    assert value > 0\n",
     "def test_value(value=5):\n    assert value == 5\n"),
    ("VALUE = -5\n\ndef test_value():\n    assert VALUE > 0\n",
     "VALUE = 5\n\ndef test_value():\n    assert VALUE == 5\n"),
    ("from calc import add\nINPUT = -5\n\ndef test_value():\n    assert add(INPUT, 0) > 0\n",
     "from calc import add\nINPUT = 5\n\ndef test_value():\n    assert add(INPUT, 0) == 5\n"),
    ("INPUT = -5\nALIAS = INPUT\n\ndef test_value():\n    assert ALIAS > 0\n",
     "INPUT = 5\nALIAS = INPUT\n\ndef test_value():\n    assert ALIAS == 5\n"),
    ("INPUT = -5\n\ndef test_value():\n    value = INPUT\n    assert value > 0\n",
     "INPUT = 5\n\ndef test_value():\n    value = INPUT\n    assert value == 5\n"),
    ("from calc import subtract as compute\n\ndef test_value():\n    assert compute(2, 3) > 0\n",
     "from calc import add as compute\n\ndef test_value():\n    assert compute(2, 3) == 5\n"),
    ("def helper():\n    return -5\n\ndef test_value():\n    assert helper() > 0\n",
     "def helper():\n    return 5\n\ndef test_value():\n    assert helper() == 5\n"),
])
def test_changed_data_or_callee_context_never_buys_restoration(before, after):
    ir, findings, verdict = _run(before, after)
    assert not ir.files[0].native_assertion_context_unchanged
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("source", [
    "from calc import add\n\ndef test_value():\n    assert add(2, 3) > 0\n",
    "from calc import add\n\ndef test_value():\n    value = add(2, 3)\n    assert value > 0\n",
    "INPUT = 5\n\ndef test_value():\n    assert INPUT > 0\n",
    "INPUT = 5\nALIAS = INPUT\n\ndef test_value():\n    assert ALIAS > 0\n",
    "INPUT = 5\n\ndef test_value():\n    value = INPUT\n    assert value > 0\n",
])
def test_unchanged_source_context_keeps_simple_strengthening(source):
    ir, findings, verdict = _run(source, source.replace("> 0", "== 5"))
    assert ir.files[0].native_assertion_context_unchanged
    assert verdict == "pass" and findings == []


def test_other_module_edits_conservatively_decline_the_context_proof():
    before = "INPUT = 5\nUNRELATED = -1\n\ndef test_value():\n    assert INPUT > 0\n"
    after = before.replace("UNRELATED = -1", "UNRELATED = 0").replace("> 0", "== 5")
    _ir, findings, verdict = _run(before, after)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_missing_optional_ir_context_never_grants_restoration():
    assert not FileIR("test_value.py", "python", "test", "modified").native_assertion_context_unchanged
    before = "from calc import add\n\ndef test_value():\n    assert add(2, 3) > 0\n"
    ir, _findings, _verdict = _run(before, before.replace("> 0", "== 5"))
    ir.files[0].native_assertion_context_unchanged = False
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in detect(ir))


@pytest.mark.parametrize("mutation", ["outside", "overlap", "text", "inherited", "missing"])
def test_unproven_native_spans_do_not_provide_context(mutation):
    source = b"def test_value():\n    assert value > 0\n"
    parsed = parse_python(source, collect_tests=True)
    assertion = parsed.units[0].side.assertions[0]
    if mutation == "outside":
        assertion.span = (0, len(source) + 1)
    elif mutation == "overlap":
        parsed.units[0].side.assertions.append(assertion)
    elif mutation == "text":
        assertion.text = "assert different > 0"
    elif mutation == "inherited":
        assertion.inherited = True
    else:
        assertion.span = None
    assert _native_assertion_context(source, parsed) is None


def test_raises_block_does_not_mask_executable_setup():
    before = (
        "import pytest\nfrom calc import add\n\ndef test_value():\n"
        "    with pytest.raises(ValueError):\n        value = add(-5, 0)\n"
        "    assert value > 0\n"
    )
    after = before.replace("add(-5, 0)", "add(5, 0)").replace("> 0", "== 5")
    ir, findings, verdict = _run(before, after)
    assert not ir.files[0].native_assertion_context_unchanged
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_another_changed_assertion_cannot_replace_the_restored_assertions_input():
    before = (
        "value = 0\ndef set_value(x):\n    global value\n    value = x\n    return 1\n\n"
        "def test_value():\n    assert set_value(-5) > 0\n    assert value > 0\n"
    )
    after = before.replace("set_value(-5)", "set_value(5)").replace("assert value > 0", "assert value == 5")
    ir, findings, verdict = _run(before, after)
    assert not ir.files[0].native_assertion_context_unchanged
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_other_unchanged_assertions_do_not_prevent_one_restoration():
    before = (
        "from calc import add\n\ndef test_value():\n"
        "    assert add(1, 1) == 2\n    assert add(2, 3) > 0\n"
    )
    ir, findings, verdict = _run(before, before.replace("> 0", "== 5"))
    assert ir.files[0].native_assertion_context_unchanged
    assert verdict == "pass" and findings == []


@pytest.mark.parametrize("other", [
    FileChange("tests/test_helper.py", "modified", b"def value():\n    return -5\n", b"def value():\n    return 5\n"),
    FileChange("calc.py", "modified", b"def value():\n    return -5\n", b"def value():\n    return 5\n"),
    FileChange("README.md", "modified", b"old docs\n", b"new docs\n"),
])
def test_other_file_change_cannot_hide_changed_callee_context(other):
    before = b"from test_helper import value\n\ndef test_value():\n    assert value() > 0\n"
    ir, findings, _verdict = analyze(
        [FileChange("tests/test_value.py", "modified", before, before.replace(b"> 0", b"== 5")), other],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
    )
    target = next(file for file in ir.files if file.path == "tests/test_value.py")
    assert not target.native_assertion_context_unchanged
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_generated_artifact_does_not_obscure_the_single_source_change():
    before = b"from calc import add\n\ndef test_value():\n    assert add(2, 3) > 0\n"
    ir, findings, verdict = analyze(
        [FileChange("tests/test_value.py", "modified", before, before.replace(b"> 0", b"== 5")),
         FileChange("tests/__pycache__/test_value.pyc", "added", None, b"generated")],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
    )
    assert ir.files[0].native_assertion_context_unchanged
    assert verdict == "pass" and findings == []


def test_rename_does_not_prove_unchanged_import_context():
    before = b"from calc import add\n\ndef test_value():\n    assert add(2, 3) > 0\n"
    ir, findings, verdict = analyze(
        [FileChange("tests/nested/test_value.py", "modified", before, before.replace(b"> 0", b"== 5"),
                    old_path="tests/test_value.py")],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
    )
    assert not ir.files[0].native_assertion_context_unchanged
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_context_uses_frontend_normalization_without_removing_other_source(newline):
    before = "# 中文😀\nfrom calc import add\n\ndef test_value():\n    assert add(2, 3) > 0\n"
    after = before.replace("> 0", "== 5")
    ir, findings, verdict = _run(before.replace("\n", newline), after)
    assert ir.files[0].native_assertion_context_unchanged
    assert verdict == "pass" and findings == []
