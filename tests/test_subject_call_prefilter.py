"""A pass-local relevance proof, not a PASS verdict for an unanalyzed file."""

import ast
import importlib.util
from pathlib import Path

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.frontends.python import subject_replacements as subject
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion, AssertionPair, FileIR, IR, Unit, UnitDelta, UnitSide
from test_issue132_subject_replacements import BASE, PREFIX, judge


PATH = "tests/test_billing.py"


def paired(left_before="total([1, 2])", left_after="total([1, 2])", before=None, after=None):
    # A focused, explicitly paired IR fixture isolates this one pass. Full
    # engine positives below independently verify real frontend/alignment use.
    old = Assertion("a0", "compare_eq", S.EXACT_VALUE,
                    f"assert {left_before} == 3", (0, 1), left=left_before,
                    right_literal="3", right_value="3")
    new = Assertion("a0", "compare_eq", S.EXACT_VALUE,
                    f"assert {left_after} == 3", (0, 1), left=left_after,
                    right_literal="3", right_value="3")
    unit = Unit("test_function", "test_total", "by_name",
                UnitSide((0, 1), assertions=[old]), UnitSide((0, 1), assertions=[new]),
                UnitDelta(assertion_pairs=[AssertionPair("a0", "a0", 0)]))
    ir = IR("owned-before", "owned-after", files=[FileIR(PATH, "python", "test", "modified", units=[unit])])
    change = FileChange(PATH, "modified", before if before is not None else BASE.encode(),
                        after if after is not None else BASE.encode())
    return ir, change, old, new


def events(ir, change):
    return subject.subject_replacement_events(ir, [change], root_reader=lambda _path: None)


def forbid_module_parse(monkeypatch):
    def forbidden(_data):
        pytest.fail("this already-excluded direct-call pair parsed the whole module")

    monkeypatch.setattr(subject, "_parse", forbidden)


@pytest.mark.parametrize("left_before,left_after", [
    ("total([1, 2])", "total([1, 2])"),
    ("billing.total([1,2])", "(billing.total)( [1, 2] )"),
    ("billing.total([1, 2])", "billing.total([3], extra=True)"),
    ("factory()(1)", "factory()(2)"),
])
def test_same_direct_callable_needs_no_module_parse(monkeypatch, left_before, left_after):
    ir, change, _old, _new = paired(left_before, left_after)
    forbid_module_parse(monkeypatch)
    assert events(ir, change) == []


@pytest.mark.parametrize("setup,callee", [("", "sum"), ("import builtins\n", "builtins.sum")])
def test_changed_direct_callable_still_parses_both_sides_and_detects(monkeypatch, setup, callee):
    after = PREFIX + setup + f"def test_total():\n    assert {callee}([1, 2]) == 3\n"
    native = subject._parse
    reads = []

    def observe(data):
        reads.append(data)
        return native(data)

    monkeypatch.setattr(subject, "_parse", observe)
    found = [finding for finding in judge(BASE, after) if finding.rule == "TEST_PATCHES_SUBJECT"]
    assert len(found) == 1 and found[0].severity == "high"
    assert "app.billing.total" in found[0].message
    assert reads == [BASE.encode(), after.encode()]


@pytest.mark.parametrize("hops", [1, 2])
def test_equal_capture_text_does_not_hide_a_changed_call(monkeypatch, hops):
    assignment = "    got = total([1, 2])\n"
    name = "got"
    if hops == 2:
        assignment += "    result = got\n"
        name = "result"
    before = PREFIX + "def test_total():\n" + assignment + f"    assert {name} == 3\n"
    after = before.replace("= total(", "= sum(")
    native = subject._parse
    reads = []

    def observe(data):
        reads.append(data)
        return native(data)

    monkeypatch.setattr(subject, "_parse", observe)
    found = [finding for finding in judge(before, after) if finding.rule == "TEST_PATCHES_SUBJECT"]
    assert len(found) == 1 and found[0].severity == "high"
    assert reads == [before.encode(), after.encode()]


@pytest.mark.parametrize("left", ["sum([1, 2])", "got", "broken(", "left + right", None])
def test_changed_unknown_or_invalid_subject_keeps_whole_source_failure(monkeypatch, left):
    ir, change, _old, _new = paired(left_after=left)
    failure = EngineError("owned existing whole-source refusal")
    reads = []

    def failed(data):
        reads.append(data)
        raise failure

    monkeypatch.setattr(subject, "_parse", failed)
    with pytest.raises(EngineError) as raised:
        events(ir, change)
    assert raised.value is failure and reads == [change.before]


@pytest.mark.parametrize("field,side,value", [
    ("form", "before", "truthy"),
    ("form", "after", "compare_ord"),
    ("positive", "before", False),
    ("positive", "after", False),
    ("right_literal", "before", None),
    ("right_literal", "after", "4"),
])
def test_original_literal_equality_eligibility_remains_first(monkeypatch, field, side, value):
    ir, change, old, new = paired()
    setattr(old if side == "before" else new, field, value)
    forbid_module_parse(monkeypatch)
    assert events(ir, change) == []


def test_other_helpers_and_parameterized_branch_keep_order_before_the_prefilter(monkeypatch):
    ir, change, _old, _new = paired()
    unit = ir.files[0].units[0]
    extra = Assertion("a1", "compare_eq", S.EXACT_VALUE, "assert value == expected", (2, 3),
                      left="value", right_literal=None, inherited=True)
    unit.after.assertions.append(extra)
    unit.delta.assertions_added.append("a1")
    calls = []
    extrema = (PATH, "test_total", "extrema", "owned", (0, 1))
    fixture = (PATH, "test_total", "fixture", "owned", (0, 1))
    parameterized = (PATH, "test_total", "parameterized", "owned", (0, 1))

    def first(*_args, **_kwargs):
        calls.append("extrema")
        return [extrema]

    def second(*_args, **_kwargs):
        calls.append("generator")
        return [fixture]

    def parse(_data):
        calls.append("module")
        return ast.Module(body=[], type_ignores=[])

    def third(*_args, **_kwargs):
        calls.append("parameterized")
        return parameterized

    monkeypatch.setattr(subject, "literal_extrema_events", first)
    monkeypatch.setattr(subject, "generator_fixture_subject_events", second)
    monkeypatch.setattr(subject, "_parse", parse)
    monkeypatch.setattr(subject, "parameterized_abs_event", third)
    assert events(ir, change) == sorted([extrema, fixture, parameterized])
    assert calls == ["extrema", "generator", "module", "module", "parameterized"]


def owned_cases():
    spec = importlib.util.spec_from_file_location(
        "subject_prefilter_owned_cases", Path(__file__).resolve().parents[1] / "tools" / "standin_cost_cases.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case", ["ordinary_1mb", "deep_expression_1mb"])
def test_original_one_megabyte_owned_pair_is_irrelevant_to_this_call_replacement_branch(monkeypatch, case):
    before, after = owned_cases().pair(case)
    assert len(before) == len(after) == 1_000_000
    ir, change, _old, _new = paired("billing.total()", "billing.total()", before, after)
    forbid_module_parse(monkeypatch)
    assert events(ir, change) == []  # Other installation passes still own the changed assignment.


def test_needed_original_ordinary_source_still_hits_the_same_node_cap():
    before, after = owned_cases().pair("ordinary_1mb")
    after = after.replace(b"assert billing.total()", b"assert sum()")
    ir, change, _old, _new = paired("billing.total()", "sum()", before, after)
    with pytest.raises(EngineError, match="subject replacement source exceeds the syntax node limit"):
        events(ir, change)


def test_unavailable_callee_dump_proof_falls_through_to_the_existing_path(monkeypatch):
    ir, change, _old, _new = paired()
    failure = EngineError("owned existing parse refusal")

    def unavailable(_node):
        raise RecursionError("owned callee formatting failure")

    def failed(_data):
        raise failure

    monkeypatch.setattr(subject, "stable_dump", unavailable)
    monkeypatch.setattr(subject, "_parse", failed)
    with pytest.raises(EngineError) as raised:
        events(ir, change)
    assert raised.value is failure


def test_invalid_whole_test_file_still_has_the_existing_unparseable_finding():
    after = BASE + "broken = (\n"
    found = [finding for finding in judge(BASE, after) if finding.rule == "TEST_FILE_UNPARSEABLE"]
    assert len(found) == 1 and found[0].severity == "high"
