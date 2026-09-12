"""Source-backed expectations retain input identity through ordinary helpers."""

import datetime
from dataclasses import replace
import json
from pathlib import Path

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


def run(before, after, *, reverse=False, include_unchanged=False):
    old = {p: s.encode() if isinstance(s, str) else s for p, s in before.items()}
    new = {p: s.encode() if isinstance(s, str) else s for p, s in after.items()}
    changes = [FileChange(path=p, before=old.get(p), after=new.get(p),
                          status="modified" if p in old and p in new else "added" if p in new else "deleted")
               for p in sorted(old.keys() | new.keys()) if include_unchanged or old.get(p) != new.get(p)]
    if reverse:
        changes.reverse()
    head = {**PROD, **new}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                   known_modules={"app"}, self_modules={"app"}, head_reader=head.get,
                   head_searcher=lambda needles: search_source_mapping(head, needles),
                   root_reader=head.get, root_searcher=lambda needles: search_source_mapping(head, needles))


def findings(result):
    return [f for f in result[1] if f.rule == RULE]


@pytest.mark.parametrize("call,owner", [("check(double(2), 4)", "EXPECTED_VALUE_CHANGED"),
                                       ("check(expected=4, actual=double(2))", RULE)])
def test_same_file_helper_actual_literal_change_blocks(call, owner):
    before = IMPORT + HELPER + "def test_double():\n    " + call + "\n"
    after = before.replace("), 4)", "), 5)").replace("expected=4", "expected=5")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    hits = [f for f in result[1] if f.rule == owner]
    assert hits and result[2] == "block"
    assert all(f.severity == "high" for f in hits)
    # The exact positional carrier is already specialized by the table
    # projector. Keyword actuals retain their ordinary named-unit provenance.
    if owner == "EXPECTED_VALUE_CHANGED":
        assert all(f.unit.startswith("test_concrete_") for f in hits)
    else:
        assert all(f.unit == "test_double" for f in hits)


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


@pytest.mark.parametrize("table,owner", [
    ("CASES = [(1, 2), (2, 4)]\n", "EXPECTED_VALUE_CHANGED"),
    ("def cases():\n    return [(1, 2), (2, 4)]\n", RULE),
])
def test_for_unpack_expectations_are_keyed_by_the_subject_input(table, owner):
    iterator = "cases()" if table.startswith("def") else "CASES"
    before = IMPORT + table + f"def test_double():\n    for value, expected in {iterator}:\n        assert double(value) == expected\n"
    after = before.replace("(1, 2), (2, 4)", "(1, 4), (2, 2), (3, 6)")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    hits = [f for f in result[1] if f.rule == owner]
    assert hits and result[2] == "block" and all(f.severity == "high" for f in hits)
    file = next(f for f in result[0].files if f.path == "tests/test_calc.py")
    if owner == "EXPECTED_VALUE_CHANGED":
        # The literal table route owns concrete assertions. Pin each input's
        # old/new answer, not merely a block or an unchanged global answer bag.
        rewritten = {(u.before.assertions[0].left, u.before.assertions[0].right_value,
                      u.after.assertions[0].right_value)
                     for u in file.units if u.before and u.after
                     and u.before.assertions[0].right_value != u.after.assertions[0].right_value}
        assert rewritten == {("double(1)", "2", "4"), ("double(2)", "4", "2")}
    else:
        assert {r[5] for r in file.expected_provenance_events} == {"app.calc.double(1)", "app.calc.double(2)"}


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


@pytest.mark.parametrize("rebound", ["check = opaque\n", "from other import opaque as check\n", "class check:\n    pass\n"])
def test_rebound_cross_file_helper_does_not_use_the_stale_definition(rebound):
    caller = IMPORT + "from .helpers import check\ndef test_double():\n    check(double(2), 4)\n"
    before = {"tests/helpers.py": HELPER + rebound, "tests/test_calc.py": caller}
    after = {**before, "tests/test_calc.py": caller.replace("), 4)", "), 5)")}
    result = run(before, after)
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_unbound_helper_local_does_not_borrow_the_module_constant():
    before = IMPORT + "expected = 4\ndef check(actual):\n    assert actual == expected\n    expected = 0\ndef test_double():\n    check(double(2))\n"
    after = before.replace("expected = 4", "expected = 5")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_provenance_budget_refuses_partial_unit_events(monkeypatch):
    monkeypatch.setattr(P, "MAX_STEPS", 1)
    before = IMPORT + HELPER + "def test_double():\n    check(double(2), 4)\n"
    after = before.replace("), 4)", "), 5)")
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_ordinary_literal_assertion_batches_reuse_native_ir_without_new_ast_work(monkeypatch):
    def unexpected_projection(*args, **kwargs):
        raise AssertionError("ordinary literal assertions must not enter provenance parsing")

    monkeypatch.setattr(P, "_module", unexpected_projection)
    before_text = IMPORT + "def test_double():\n    value = double(2)\n    assert value == 4\n"
    after_text = before_text.replace("== 4", "is not None")
    before = {f"tests/test_calc_{i}.py": before_text for i in range(30)}
    after = {p: after_text if i % 3 == 0 else before_text for i, p in enumerate(before)}
    result = run(before, after, include_unchanged=True)
    assert result[2] == "block"
    assert all(not f.expected_provenance_events for f in result[0].files)


def test_invalid_serialized_events_cannot_be_used_as_findings():
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = before.replace("== 4", "== 5")
    ir = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})[0]
    ir.files[0].expected_provenance_events = [("invalid",)]
    with pytest.raises(EngineError, match="expected provenance"):
        detect(ir, [])


@pytest.mark.parametrize("case,old,new", [
    ("EXT_004_ceil_div", "(a + b - 1) // b", "(a + b - 1) // b + 1"),
    ("EXT_014_product", "math.prod(xs)", "math.prod(xs) + 1"),
    ("EXT_021_truncate", "== expected", "== expected + '!'"),
])
@pytest.mark.parametrize("changed", [False, True])
def test_closed_helper_expressions_preserve_honest_cases_but_block_different_results(case, old, new, changed):
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "refactors" / "cases" / case
    tree = lambda folder: {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*.py")}
    prod, before, after = tree(root / "PROD-GOOD"), tree(root / "BEFORE"), tree(root / "AFTER")
    if changed:
        after = {p: data.replace(old.encode(), new.encode()) for p, data in after.items()}
    result = run({**prod, **before}, {**prod, **after})
    assert bool(findings(result)) is changed
    assert result[2] == ("block" if changed else "pass")


@pytest.mark.parametrize("import_line,call", [("import math as m", "m.prod"),
                                             ("from math import prod as multiply", "multiply")])
def test_math_import_aliases_have_the_same_closed_literal_result(import_line, call):
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + import_line + f"\ndef check(x):\n    assert double(x) == {call}([2, 2])\ndef test_double():\n    check(2)\n"
    assert not findings(run({"tests/test_calc.py": before}, {"tests/test_calc.py": after}))


@pytest.mark.parametrize("shadow", ["math.py", "math/__init__.py", "tests/math.py", "conftest.py"])
def test_shadowed_or_mutated_math_has_no_constant_call_authority(shadow):
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + "import math\ndef check(x):\n    assert double(x) == math.prod([2, 2])\ndef test_double():\n    check(2)\n"
    shadow_source = "import math\nmath.prod = lambda values: 0\n" if shadow == "conftest.py" else "def prod(values):\n    return 0\n"
    result = run({"tests/test_calc.py": before, shadow: shadow_source}, {"tests/test_calc.py": after, shadow: shadow_source})
    assert findings(result) and result[2] == "block"


def test_rebound_math_alias_does_not_keep_import_authority():
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + "import math as m\nm = object()\ndef check(x):\n    assert double(x) == m.prod([2, 2])\ndef test_double():\n    check(2)\n"
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"


@pytest.mark.parametrize("literal", [repr(1 << 300), repr("x" * 4097)])
def test_oversized_literal_computation_is_unknown_not_equal(literal):
    zero = "''" if literal.startswith("'") else "0"
    before = IMPORT + f"def test_double():\n    assert double(2) == {literal}\n"
    after = IMPORT + f"def check(x):\n    assert double(x) == {literal} + {zero}\ndef test_double():\n    check(2)\n"
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"


def test_unknown_computation_is_not_silently_equal_to_the_old_literal():
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + "def check(x):\n    expected = unknown_answer(x)\n    assert double(x) == expected\ndef test_double():\n    check(2)\n"
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"


def test_closed_expression_specialization_retains_input_keys_through_multiple_bindings():
    helper = "def check(actual, expected):\n    answer = expected + 0\n    alias = answer\n    assert actual == alias\n"
    before = IMPORT + helper + "def test_double():\n    check(double(1), 1 + 1)\n    check(double(2), 2 + 2)\n"
    after = before.replace("double(1), 1 + 1", "double(1), 2 + 2").replace("double(2), 2 + 2", "double(2), 1 + 1")
    after += "    check(double(3), 3 + 3)\n"
    result = run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert findings(result) and result[2] == "block"
    assert {r[5] for file in result[0].files for r in file.expected_provenance_events} == {"app.calc.double(1)", "app.calc.double(2)"}
