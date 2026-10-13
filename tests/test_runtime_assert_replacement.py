"""Owned assertEqual replacement controls; source expectations await review.

Run through ordinary hosted pytest only. Draft preparation does not execute
these modules, analyzed native APIs, product code or a fixture-label change.
"""
import ast
import datetime
import hashlib
import json
from pathlib import Path

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors import test_disabled
from checkwash.engine import analyze
from checkwash.frontends.python.conftest_controls import RUNTIME, is_collection_control, marker_kind
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.unittest_assertion_controls import unittest_assertion_controls

MARKER = "conftest.runtime.unittest.TestCase.assertEqual-noop"
TARGET = "unittest.TestCase.assertEqual"
LAMBDA = "lambda self, *args, **kwargs: None"
NOOP = TARGET + " = " + LAMBDA
ORIGINAL = "original = " + TARGET
FIXED_SHA256 = "31f044a158c300fe036a55ba44bf470f6bfd2eec01fb9c4013f5d439210e15f4"


def source(body):
    return "import unittest\n" + body + "\n"


def effects(text):
    return list(unittest_assertion_controls(ast.parse(text)))


def judged(before, after, path="conftest.py"):
    change = FileChange(path, "modified", before.encode(), after.encode())
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 12))


@pytest.mark.parametrize("body", [
    pytest.param(NOOP, id="exact-noop"),
    pytest.param("pass\n" + NOOP, id="inert-statement"),
    pytest.param("if True:\n    " + NOOP, id="literal-live"),
    pytest.param("if not False:\n    " + NOOP, id="literal-not-live"),
    pytest.param("if False:\n    pass\nelse:\n    " + NOOP, id="literal-else"),
    pytest.param("noop = " + LAMBDA + "\n" + TARGET + " = noop", id="known-noop-value"),
    pytest.param(NOOP + "\nunittest = None", id="root-rebound-after"),
    pytest.param(ORIGINAL + "\n" + NOOP + "\noriginal = None", id="capture-rebound-not-restored"),
    pytest.param(NOOP + "\nsaved = " + TARGET + "\n" + TARGET + " = saved", id="capture-after-noop"),
    pytest.param(ORIGINAL + "\n" + NOOP + "\nsaved = " + TARGET + "\n"
                 + TARGET + " = original\n" + TARGET + " = saved", id="restore-then-saved-noop"),
    pytest.param("def arbitrary(self, *args, **kwargs):\n    return original(self, *args, **kwargs)\n"
                 + TARGET + " = arbitrary\n" + NOOP, id="unknown-overwrite-then-known-noop"),
    pytest.param("def inert():\n    " + NOOP + "\n" + NOOP, id="uncalled-body-is-inert"),
    pytest.param(NOOP + "\ndef unittest():\n    pass", id="definition-rebind-does-not-restore"),
])
def test_final_known_noop_keeps_one_effect_and_real_assignment_evidence(body):
    text = source(body)
    found = effects(text)
    assert len(found) == 1 and found[0][0] == MARKER
    assert isinstance(found[0][1], ast.Assign)
    assert ".assertEqual =" in ast.get_source_segment(text, found[0][1])
    assert marker_kind(MARKER) == RUNTIME and not is_collection_control(MARKER)


@pytest.mark.parametrize("text", [
    "import unittest as ut\nut.TestCase.assertEqual = " + LAMBDA,
    "from unittest import TestCase\nTestCase.assertEqual = " + LAMBDA,
    "from unittest import TestCase as Case\nCase.assertEqual = " + LAMBDA,
    "from unittest import TestCase as Case\nCase.assertEqual = " + LAMBDA + "\nCase = None",
    "import unittest\nunittest = None\nimport unittest\n" + NOOP,
])
def test_direct_native_import_authority_is_temporal_and_alias_spelling_is_not_identity(text):
    assert [name for name, _ in effects(text)] == [MARKER]


@pytest.mark.parametrize("body", [
    pytest.param(ORIGINAL + "\n" + NOOP + "\n" + TARGET + " = original", id="restore-same-original"),
    pytest.param(ORIGINAL + "\n" + NOOP + "\nfrom unittest import TestCase as Case\n"
                 + "Case.assertEqual = original", id="restore-through-second-direct-import"),
    pytest.param("from unittest import TestCase as Case\noriginal = Case.assertEqual\n"
                 + NOOP + "\n" + TARGET + " = original", id="capture-through-second-direct-import"),
    pytest.param(NOOP + "\n" + TARGET + " = lambda self, *args, **kwargs: original(self, *args, **kwargs)",
                 id="unknown-lambda-overwrite"),
    pytest.param(ORIGINAL + "\ndef delegated(self, *args, **kwargs):\n"
                 + "    return original(self, *args, **kwargs)\n" + NOOP + "\n"
                 + TARGET + " = delegated", id="known-original-delegate-overwrite"),
    pytest.param(NOOP + "\n" + TARGET + " = None", id="invalid-callable-not-noop"),
    pytest.param(NOOP + "\n" + TARGET + " = unavailable", id="unresolved-final-read"),
    pytest.param("unittest = None\n" + NOOP, id="root-rebound-before"),
    pytest.param("def unittest():\n    pass\n" + NOOP, id="root-definition-before"),
    pytest.param("if False:\n    " + NOOP, id="dead-branch"),
    pytest.param("def unused():\n    " + NOOP, id="uncalled-function"),
    pytest.param(NOOP + "\nif condition:\n    " + TARGET + " = original", id="unknown-predicate"),
    pytest.param("try:\n    " + NOOP + "\nfinally:\n    pass", id="unsupported-try"),
    pytest.param("for entry in values:\n    " + NOOP, id="unsupported-loop"),
    pytest.param(NOOP + "\nraise RuntimeError('stop')", id="module-cannot-complete"),
    pytest.param(NOOP + "\nunittest.TestCase = None", id="native-class-attribute-overwrite"),
    pytest.param(NOOP + "\n" + TARGET + "()", id="direct-call-after"),
    pytest.param(TARGET + "()\n" + NOOP, id="direct-call-before"),
    pytest.param(NOOP + "\nexternal()", id="unknown-call-after"),
    pytest.param(NOOP + "\ndef helper(value=external()):\n    pass", id="default-executes"),
    pytest.param(NOOP + "\n@external\ndef helper():\n    pass", id="decorator-executes"),
    pytest.param(NOOP + "\ndef helper(value: external()):\n    pass", id="annotation-work-unknown"),
    pytest.param(NOOP + "\nunrelated = missing", id="unknown-read-after"),
    pytest.param("alias = unittest\nalias.TestCase.assertEqual = " + LAMBDA, id="assigned-module-alias-residual"),
    pytest.param("Case = unittest.TestCase\nCase.assertEqual = " + LAMBDA, id="assigned-class-alias-residual"),
    pytest.param("setattr(unittest.TestCase, 'assertEqual', " + LAMBDA + ")", id="dynamic-setattr-residual"),
    pytest.param("unittest.TestCase.assertTrue = " + LAMBDA, id="other-api-not-native-target"),
    pytest.param(NOOP + "\nimport custom", id="unrelated-import-effects-unknown"),
])
def test_restored_dead_unknown_or_other_target_does_not_mint_the_new_effect(body):
    assert effects(source(body)) == []


@pytest.mark.parametrize("text", [
    "import custom as unittest\n" + NOOP,
    "from custom import TestCase\nTestCase.assertEqual = " + LAMBDA,
    "from .unittest import TestCase\nTestCase.assertEqual = " + LAMBDA,
    "from unittest import *\nTestCase.assertEqual = " + LAMBDA,
    "import unittest.case as unittest\n" + NOOP,
    "class TestCase:\n    pass\nTestCase.assertEqual = " + LAMBDA,
    "from unittest import TestCase\nTestCase = None\nTestCase.assertEqual = " + LAMBDA,
])
def test_custom_relative_shadowed_and_submodule_spellings_do_not_supply_native_authority(text):
    assert effects(text) == []


@pytest.mark.parametrize("replacement", [
    "lambda: None",                         # Cannot accept the bound receiver or operands.
    "lambda self: None",                    # Cannot accept both compared operands.
    "lambda self, *args: None",              # Not the admitted keyword-compatible signature.
    "lambda self, **kwargs: None",           # Cannot accept both positional operands.
    "lambda self, *args, flag, **kwargs: None",  # Required keyword may raise instead.
    "lambda self=None, *args, **kwargs: None",
    "lambda self, /, *args, **kwargs: None",  # Explicitly outside this first signature.
    "lambda self, *args, **kwargs: False",   # No broad callable-body inference.
    "lambda self, *args, **kwargs: original(self, *args, **kwargs)",
])
def test_only_the_supported_zero_validation_signature_is_proved(replacement):
    assert effects(source(TARGET + " = " + replacement)) == []


def test_receiver_and_variadic_parameter_names_do_not_change_the_literal_noop():
    text = source(TARGET + " = lambda receiver, *positional, **named: None")
    assert [name for name, _ in effects(text)] == [MARKER]


def test_capture_after_replacement_points_evidence_at_the_final_real_write():
    text = source(NOOP + "\noriginal = " + TARGET + "\n" + TARGET + " = original")
    found = effects(text)
    assert found[0][0] == MARKER and found[0][1].lineno == 4
    assert ast.get_source_segment(text, found[0][1]) == TARGET + " = original"


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_existing_warning_gate_shape_and_real_source_evidence_are_preserved(path):
    text = source(NOOP)
    ir, findings, verdict = judged("# no replacement\n", text, path)
    raw = [finding for finding in test_disabled.detect(ir) if MARKER in finding.message]
    assert len(raw) == 1 and raw[0].severity == "warn"
    hits = [finding for finding in findings if MARKER in finding.message]
    assert verdict == "block" and len(hits) == 1 and hits[0].severity == "high"
    assert hits[0].shape == "collection_control" and hits[0].path == path
    start = text.index(NOOP)
    assert hits[0].after.text == NOOP and hits[0].after.span == (start, start + len(NOOP))
    assert text[:start].count("\n") + 1 == 2
    assert "execution/report suppression" in hits[0].message


def test_existing_noop_reformatting_and_direct_import_alias_change_are_not_new_effects():
    before = source(NOOP)
    after = "from unittest import TestCase as Case\n# formatting only\nCase.assertEqual = (lambda self, *a, **k: None)\n"
    assert [name for name, _ in effects(before)] == [name for name, _ in effects(after)]
    assert judged(before, after)[1:] == ([], "pass")


def test_fingerprint_does_not_follow_source_line_numbers():
    first = judged("# no replacement\n", source(NOOP))[1]
    second = judged("# no replacement\n", "\n\n" + source(NOOP))[1]
    assert len(first) == len(second) == 1
    assert first[0].fingerprint == second[0].fingerprint


def test_ordinary_module_does_not_acquire_this_conftest_suite_marker():
    parsed = parse_python(source(NOOP).encode(), collect_tests=True, conftest=False)
    assert not [marker for unit in parsed.units for marker in unit.side.markers if marker.name == MARKER]


def test_unknown_new_channel_does_not_clear_an_existing_runtime_detection():
    text = source(NOOP) + "import custom\ndef pytest_runtest_protocol(item, nextitem):\n    return True\n"
    assert effects(text) == []
    findings = judged("# no runtime control\n", text)[1]
    assert any("pytest_runtest_protocol.call-skipped" in finding.message for finding in findings)


def test_exact_pr376_assert_pairs_reuse_source_bytes_and_keep_item_family_separate():
    raw = (Path(__file__).resolve().parents[1] / "tools/runtime_api_pairs.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXED_SHA256
    fixed = {case["id"]: case for case in json.loads(raw)["cases"]}
    for name, expected in (("RT-ASSERT-NOOP", "block"), ("RT-ASSERT-DELEGATE", "pass")):
        files = fixed[name]["files"]["conftest.py"]
        _ir, findings, verdict = judged(files["before"], files["after"])
        assert verdict == expected
        assert len([finding for finding in findings if MARKER in finding.message]) == (name == "RT-ASSERT-NOOP")
    for name in ("RT-ITEM-NOOP", "RT-ITEM-DELEGATE"):
        assert effects(fixed[name]["files"]["conftest.py"]["after"]) == []
