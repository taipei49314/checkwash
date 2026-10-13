"""Owned item.runtest proof and controls; new expectations await review.

Ordinary hosted pytest only. No fixture labels, native API execution or
product invocation was performed while preparing this source proposal.
"""
import ast
import datetime
import hashlib
import json
from pathlib import Path
import textwrap

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors import test_disabled
from checkwash.engine import analyze
from checkwash.frontends.python.conftest_controls import RUNTIME, is_collection_control, marker_kind
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.item_callback_controls import item_callback_controls

MARKER = "conftest.runtime.pytest_runtest_call.item-runtest-noop"
NOOP = "item.runtest = lambda: None"
FIXED_SHA256 = "31f044a158c300fe036a55ba44bf470f6bfd2eec01fb9c4013f5d439210e15f4"


def source(body, provider="import pytest", decorator="pytest.hookimpl(tryfirst=True)"):
    return provider + "\n@" + decorator + "\ndef pytest_runtest_call(item):\n" + textwrap.indent(body, "    ") + "\n"


def effects(text):
    return list(item_callback_controls(ast.parse(text)))


def judged(before, after, path="conftest.py"):
    change = FileChange(path, "modified", before.encode(), after.encode())
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 11))


@pytest.mark.parametrize("body", [
    NOOP,
    "pass\n" + NOOP,
    "if True:\n    " + NOOP,
    "if False:\n    pass\nelse:\n    " + NOOP,
    "native = item\nnative.runtest = lambda: None",
    "saved = item.runtest\n" + NOOP + "\nitem = None",  # Name change does not restore the object.
    "saved = item.runtest\n" + NOOP + "\nsaved = None",  # Rebinding a capture is not restoration.
    "def unknown_callable():\n    return original()\nitem.runtest = unknown_callable\n" + NOOP,
    NOOP + "\nsaved_noop = item.runtest\nitem.runtest = saved_noop",
    NOOP + "\nreturn\nitem.runtest = other",
    "def unused():\n    return\n" + NOOP,
])
def test_final_noop_is_a_runtime_effect_with_real_assignment_evidence(body):
    text = source(body)
    found = effects(text)
    assert len(found) == 1 and found[0][0] == MARKER
    assert isinstance(found[0][1], ast.Assign)
    assert ".runtest =" in ast.get_source_segment(text, found[0][1])
    assert marker_kind(MARKER) == RUNTIME and not is_collection_control(MARKER)


@pytest.mark.parametrize("body", [
    "original = item.runtest\n" + NOOP + "\nitem.runtest = original",
    "original = item.runtest\nnative = item\n" + NOOP + "\nnative.runtest = original",
    NOOP + "\nitem.runtest = unknown_callable",
    "def delegated():\n    return original()\n" + NOOP + "\nitem.runtest = delegated",
    NOOP + "\nunrelated = missing_name",
    NOOP + "\nitem.runtest = lambda: original()",
    "item = None\n" + NOOP,
    "custom = None\ncustom.runtest = lambda: None",
    "return\n" + NOOP,
    "raise RuntimeError()\n" + NOOP,
    NOOP + "\nraise RuntimeError()",
    "if False:\n    " + NOOP,
    "def unused():\n    " + NOOP,
    "if flag:\n    " + NOOP,
    NOOP + "\nif flag:\n    item.runtest = original",
    "try:\n    " + NOOP + "\nfinally:\n    pass",
    "for entry in items:\n    " + NOOP,
    NOOP + "\nexternal(item)",
    "item.runtest()\n" + NOOP,
    "item.runtest = lambda unused=side_effect(): None",
    "item.runtest = lambda argument: None",
    "item.obj = lambda: None",
    NOOP + "\nif False:\n    yield",
    NOOP + "\nreturn\nyield",
])
def test_restore_dead_unknown_or_other_targets_do_not_mint_the_new_effect(body):
    assert effects(source(body)) == []


@pytest.mark.parametrize("provider,decorator", [
    ("import pytest as pt", "pt.hookimpl(tryfirst=True)"),
    ("from pytest import hookimpl as hook", "hook(tryfirst=True)"),
])
def test_direct_native_import_aliases_are_bound_at_definition(provider, decorator):
    assert [name for name, _ in effects(source(NOOP, provider, decorator))] == [MARKER]


@pytest.mark.parametrize("text", [
    source(NOOP, "import custom as pytest"),
    source(NOOP, "import pytest\npytest = None"),
    source(NOOP, "from custom import hookimpl", "hookimpl(tryfirst=True)"),
    source(NOOP, decorator="pytest.hookimpl(trylast=True)"),
    source(NOOP, decorator="pytest.hookimpl(wrapper=True)"),
    source(NOOP).replace("(item):", "(custom):"),
    source(NOOP).replace("def pytest_", "async def pytest_"),
    source(NOOP).replace("def pytest_runtest_call", "def pytest_runtest_setup"),
    source(NOOP) + "pytest_runtest_call = None\n",
    source(NOOP) + "def pytest_runtest_call(item):\n    pass\n",
    source(NOOP) + "if flag:\n    pytest_runtest_call = other\n",
    source(NOOP) + "from custom import *\n",
    source(NOOP) + "pytest.hookimpl = custom\n",
    source(NOOP) + "unrelated = missing_name\n",
    source(NOOP).replace("@pytest.hookimpl(tryfirst=True)\n", ""),
])
def test_unproved_import_signature_order_or_final_hook_binding_is_not_accepted(text):
    assert effects(text) == []


def test_import_name_rebinding_after_definition_does_not_undo_applied_decorator():
    assert [name for name, _ in effects(source(NOOP) + "pytest = None\n")] == [MARKER]


def test_capture_after_noop_is_not_the_original_and_cannot_falsely_restore_it():
    text = source(NOOP + "\noriginal = item.runtest\nitem.runtest = original")
    found = effects(text)
    assert found[0][0] == MARKER and found[0][1].lineno == 6


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_new_effect_uses_existing_warn_detector_and_gate_without_relabelling(path):
    text = source(NOOP)
    ir, findings, verdict = judged("# no hook\n", text, path)
    raw = [finding for finding in test_disabled.detect(ir) if MARKER in finding.message]
    assert len(raw) == 1 and raw[0].severity == "warn"
    hits = [finding for finding in findings if MARKER in finding.message]
    assert verdict == "block" and len(hits) == 1 and hits[0].severity == "high"
    assert hits[0].shape == "collection_control" and hits[0].path == path
    start = text.index(NOOP)
    assert hits[0].after.text == NOOP and hits[0].after.span == (start, start + len(NOOP))
    assert text[:start].count("\n") + 1 == 4
    assert "execution/report suppression" in hits[0].message


def test_existing_noop_and_equivalent_formatting_do_not_repeat_a_finding():
    before = source(NOOP)
    after = source("# formatting only\nitem.runtest = (lambda : None)")
    assert [name for name, _ in effects(before)] == [name for name, _ in effects(after)]
    assert judged(before, after)[1:] == ([], "pass")


def test_noop_marker_fingerprint_does_not_follow_source_line_numbers():
    first = judged("# no hook\n", source(NOOP))[1]
    second = judged("# no hook\n", "\n\n" + source(NOOP))[1]
    assert len(first) == len(second) == 1
    assert first[0].fingerprint == second[0].fingerprint


def test_non_conftest_module_does_not_acquire_this_suite_control():
    parsed = parse_python(source(NOOP).encode(), collect_tests=True, conftest=False)
    assert not [m for unit in parsed.units for m in unit.side.markers if m.name == MARKER]


def test_the_two_exact_item_pairs_reuse_unchanged_pr376_bytes():
    raw = (Path(__file__).resolve().parents[1] / "tools/runtime_api_pairs.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXED_SHA256
    fixed = {case["id"]: case for case in json.loads(raw)["cases"]}
    for name, expected in (("RT-ITEM-NOOP", "block"), ("RT-ITEM-DELEGATE", "pass")):
        files = fixed[name]["files"]["conftest.py"]
        _ir, findings, verdict = judged(files["before"], files["after"])
        assert verdict == expected
        assert len([finding for finding in findings if MARKER in finding.message]) == (name == "RT-ITEM-NOOP")
    # The second family is retained as source evidence, not implemented here.
    for name in ("RT-ASSERT-NOOP", "RT-ASSERT-DELEGATE"):
        assert effects(fixed[name]["files"]["conftest.py"]["after"]) == []
