"""Source-backed expectations retain input identity through ordinary helpers."""

import datetime
from dataclasses import replace
import json

import pytest

from checkwash.change import EngineError
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.expected_provenance import detect
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python import expected_provenance as P
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.ir.model import to_jsonable

RULE = "EXPECTATION_DEFINITION_CHANGED"
PROD = {"src/app/__init__.py": b"", "src/app/calc.py": b"def double(x):\n    return x * 2\n"}
IMPORT = "from app.calc import double\n"
HELPER = "def check(actual, expected):\n    assert actual == expected\n"


def run(before, after, *, reverse=False):
    old = {p: s.encode() if isinstance(s, str) else s for p, s in before.items()}
    new = {p: s.encode() if isinstance(s, str) else s for p, s in after.items()}
    changes = [FileChange(path=p, before=old.get(p), after=new.get(p),
                          status="modified" if p in old and p in new else "added" if p in new else "deleted")
               for p in sorted(old.keys() | new.keys()) if old.get(p) != new.get(p)]
    if reverse:
        changes.reverse()
    head = {**PROD, **new}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                   known_modules={"app"}, self_modules={"app"}, head_reader=head.get,
                   head_searcher=lambda needles: search_source_mapping(head, needles),
                   root_reader=head.get, root_searcher=lambda needles: search_source_mapping(head, needles))


def findings(result):
    return [f for f in result[1] if f.rule == RULE]


@pytest.mark.parametrize("call", ["check(double(2), 4)", "check(expected=4, actual=double(2))"])
def test_same_file_helper_actual_literal_change_blocks(call):
    before = IMPORT + HELPER + "def test_double():\n    " + call + "\n"
    after = before.replace("), 4)", "), 5)").replace("expected=4", "expected=5")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"
    assert all(f.unit == "test_double" and f.severity == "high" for f in findings(result))


@pytest.mark.parametrize("module,import_line", [
    ("tests/helpers.py", "from .helpers import check\n"),
    ("tests/helpers.py", "from tests.helpers import check\n"),
    ("tests/helpers.py", "from helpers import check\n"),
    ("tests/helpers.py", "from tests import helpers\n"),
])
def test_cross_file_helper_actuals_are_substituted(module, import_line):
    function = "helpers.check" if "from tests import helpers" in import_line else "check"
    before = {module: HELPER, "tests/test_calc.py": IMPORT + import_line + f"def test_double():\n    {function}(double(2), 4)\n"}
    after = {**before, "tests/test_calc.py": before["tests/test_calc.py"].replace("), 4)", "), 5)")}
    result = run(before, after)
    assert findings(result) and result[2] == "block"


@pytest.mark.parametrize("expected", ["4", "round(2 * 2)"])
def test_cross_file_helper_local_origin_survives_specialization_and_reverse_discovery(expected):
    helper = f"def check(actual):\n    expected = {expected}\n    assert actual == expected\n"
    caller = IMPORT + "from .helpers import check\ndef test_double():\n    check(double(2))\n"
    before = {"tests/helpers.py": helper, "tests/test_calc.py": caller}
    after = {**before, "tests/helpers.py": helper.replace(expected, "5")}
    result = run(before, after)
    assert findings(result) and result[2] == "block"
    assert findings(result)[0].path == "tests/test_calc.py"
    assert expected in findings(result)[0].message


def test_helper_keyword_only_literal_default_remains_an_origin():
    before = {"tests/helpers.py": "def check(actual, *, expected=4):\n    assert actual == expected\n",
              "tests/test_calc.py": IMPORT + "from .helpers import check\ndef test_double():\n    check(double(2))\n"}
    after = {**before, "tests/helpers.py": before["tests/helpers.py"].replace("expected=4", "expected=5")}
    assert findings(run(before, after))


def test_same_file_helper_local_origin_survives_actual_specialization():
    before = IMPORT + "def check(actual):\n    expected = 4\n    assert actual == expected\ndef test_double():\n    check(double(2))\n"
    after = before.replace("expected = 4", "expected = 5")
    assert findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))


def test_helper_input_only_change_does_not_rewrite_an_existing_answer():
    before = IMPORT + HELPER + "def test_double():\n    check(double(2), 4)\n"
    after = before.replace("double(2)", "double(3)")
    assert not findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))


@pytest.mark.parametrize("table", [
    "CASES = [(1, 2), (2, 4)]\n",
    "def cases():\n    return [(1, 2), (2, 4)]\n",
])
def test_for_unpack_expectations_are_keyed_by_the_subject_input(table):
    iterator = "cases()" if table.startswith("def") else "CASES"
    before = IMPORT + table + f"def test_double():\n    for value, expected in {iterator}:\n        assert double(value) == expected\n"
    after = before.replace("(1, 2), (2, 4)", "(1, 4), (2, 2), (3, 6)")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"
    records = next(f for f in result[0].files if f.path == "tests/test_calc.py").expected_provenance_events
    assert {r[5] for r in records} == {"app.calc.double(1)", "app.calc.double(2)"}


def test_for_unpack_and_helper_actuals_compose_without_losing_rows():
    before = IMPORT + HELPER + "def test_double():\n    for value, expected in [(1, 2), (2, 4)]:\n        check(double(value), expected)\n"
    after = before.replace("(1, 2), (2, 4)", "(1, 5), (2, 4), (3, 6)")
    assert findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))


@pytest.mark.parametrize("wanted,changed", [("4", False), ("5", True)])
def test_literal_to_fresh_local_preserves_honest_extraction(wanted, changed):
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + f"def test_double():\n    expected = {wanted}\n    assert double(2) == expected\n"
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert bool(findings(result)) is changed


@pytest.mark.parametrize("rows", [
    "(2, 4), (1, 2)",                 # whole-row reorder
    "(1, 2), (2, 4), (3, 6)",         # padding a new input
    "(1, 2), (1, 2), (2, 4)",         # duplicate an unchanged row
    "(1, 2)",                        # a deleted row is not an expected rewrite
    "(1, 2), (3, 4)",                # input-only edit
])
def test_loop_addition_reorder_and_input_only_controls(rows):
    before = IMPORT + "def test_double():\n    for value, expected in [(1, 2), (2, 4)]:\n        assert double(value) == expected\n"
    after = before.replace("(1, 2), (2, 4)", rows)
    assert not findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))


def test_multiple_helper_calls_are_paired_by_input_not_call_order_or_global_answer_bag():
    before = IMPORT + HELPER + "def test_double():\n    check(double(1), 2)\n    check(double(2), 4)\n"
    reordered = IMPORT + HELPER + "def test_double():\n    check(double(2), 4)\n    check(double(1), 2)\n"
    assert not findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": reordered}))
    swapped = reordered.replace("double(2), 4", "double(2), 2").replace("double(1), 2", "double(1), 4")
    assert findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": swapped}))


def test_existing_module_binding_detector_does_not_get_a_duplicate_finding():
    before = IMPORT + "EXPECTED = 4\ndef test_double():\n    assert double(2) == EXPECTED\n"
    after = before.replace("EXPECTED = 4", "EXPECTED = 5")
    assert len(findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))) == 1


def test_existing_concrete_root_projection_keeps_its_literal_detector_owner():
    before = {"tests/test_calc.py": IMPORT + "def test_double():\n    assert double(2) == 4\n"}
    after = {"tests/test_calc.py": IMPORT + "from test_helpers import check\ndef test_double():\n    check(double(2), 5)\n", "test_helpers.py": HELPER}
    result = run(before, after)
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in result[1])
    assert not findings(result)


def test_events_keep_json_array_and_diff_order_stability():
    before = {"tests/helpers.py": HELPER, "tests/test_calc.py": IMPORT + "from .helpers import check\ndef test_double():\n    check(double(2), 4)\n"}
    after = {"tests/helpers.py": "# unchanged helper behavior\n" + HELPER,
             "tests/test_calc.py": before["tests/test_calc.py"].replace("), 4)", "), 5)")}
    first, second = run(before, after), run(before, after, reverse=True)
    assert [f.fingerprint for f in findings(first)] == [f.fingerprint for f in findings(second)]
    ir = first[0]
    serialized = json.loads(json.dumps(to_jsonable(ir)))
    rebuilt = replace(ir, files=[replace(file, expected_provenance_events=data["expected_provenance_events"])
                                for file, data in zip(ir.files, serialized["files"])])
    assert [f.fingerprint for f in detect(ir, [])] == [f.fingerprint for f in detect(rebuilt, [])]


def test_unsupported_dynamic_loop_does_not_invent_concrete_rows():
    before = IMPORT + "def test_double():\n    for value, expected in make_cases():\n        assert double(value) == expected\n"
    after = before.replace("expected\n", "5\n")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_ambiguous_absolute_helper_import_does_not_invent_a_target():
    caller = IMPORT + "from helpers import check\ndef test_double():\n    check(double(2), 4)\n"
    before = {"tests/helpers.py": HELPER, "helpers.py": HELPER, "tests/test_calc.py": caller}
    after = {**before, "tests/test_calc.py": caller.replace("), 4)", "), 5)")}
    result = run(before, after)
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_provenance_budget_refuses_partial_unit_events(monkeypatch):
    monkeypatch.setattr(P, "MAX_STEPS", 1)
    before = IMPORT + HELPER + "def test_double():\n    check(double(2), 4)\n"
    after = before.replace("), 4)", "), 5)")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_invalid_serialized_events_cannot_be_used_as_findings():
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = before.replace("== 4", "== 5")
    ir = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})[0]
    ir.files[0].expected_provenance_events = [("invalid",)]
    with pytest.raises(EngineError, match="expected provenance"):
        detect(ir, [])
