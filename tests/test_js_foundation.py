"""Independent boundary and value regressions for the first JS/TS expansion.

These inputs deliberately do not derive from frontend matcher tables. Existing
assertion inventories and gate outcomes remain separate, unchanged contracts.
"""

import copy
import datetime
import json
from pathlib import Path
import runpy

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript


def _source(body, imports="", callback="() => {{ {body} }}"):
    return imports + '\ntest("sample", ' + callback.format(body=body) + ");\n"


def _assertions(source):
    return [assertion for unit in parse_javascript(source.encode()).units
            for assertion in unit.side.assertions]


def _analyze(before, after, path="tests/foundation.test.ts"):
    return analyze(
        [FileChange(path, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )


@pytest.mark.parametrize("callback", [
    "() => {{ {body} }}",
    "function () {{ {body} }}",
    "function named() {{ {body} }}",
    "async () => {{ {body} }}",
    "{{ timeout: 1000 }}, () => {{ {body} }}",
])
def test_only_the_actual_callback_owns_assertions(callback):
    source = (
        "expect(before()).toBe(0);\n"
        + _source("expect(inside()).toBe(1);", callback=callback)
        + "expect(after()).toBe(2);\n"
    )
    unit, = parse_javascript(source.encode()).units
    assert [a.left for a in unit.side.assertions] == ["inside()"]
    assert unit.span[1] <= source.index("expect(after())")
    gaps = javascript_coverage_gaps(source.encode(), parse_javascript(source.encode()),
                                    "tests/foundation.test.ts", "after")
    assert [gap.callee for gap in gaps] == ["expect(...).toBe", "expect(...).toBe"]


@pytest.mark.parametrize("callback", [
    "() => expect(inside()).toBe(1)",
    "value => expect(inside(value)).toBe(1)",
])
def test_concise_arrow_callback_ends_before_the_next_statement(callback):
    source = f'test("sample", {callback}); expect(outside()).toBe(2);'
    unit, = parse_javascript(source.encode()).units
    assert len(unit.side.assertions) == 1
    assert unit.side.assertions[0].left in {"inside()", "inside(value)"}
    assert unit.side.assertions[0].text.endswith(".toBe(1)")


def test_nested_test_has_its_own_assertions_and_does_not_steal_the_outer_tail():
    source = '''test("outer", () => {
  expect(before()).toBe(1);
  test("inner", () => { expect(inside()).toBe(2); });
  expect(after()).toBe(3);
});
expect(outside()).toBe(4);
'''
    outer, inner = parse_javascript(source.encode()).units
    assert (outer.qualname, inner.qualname) == ("outer", "inner")
    assert [a.left for a in outer.side.assertions] == ["before()", "after()"]
    assert [a.left for a in inner.side.assertions] == ["inside()"]
    assert [a.id for a in outer.side.assertions] == ["a0", "a1"]
    assert [a.id for a in inner.side.assertions] == ["a0"]


def test_todo_without_callback_cannot_own_a_later_assertion():
    source = 'test.todo("later"); expect(outside()).toBe(2);'
    unit, = parse_javascript(source.encode()).units
    assert unit.qualname == "later"
    assert [marker.name for marker in unit.side.markers] == ["test.skip"]
    assert unit.side.assertions == []


@pytest.mark.parametrize("helper", [
    "function unused() { expect(fake()).toBe(0); }",
    "const unused = () => { expect(fake()).toBe(0); };",
    "const unused = () => expect(fake()).toBe(0);",
])
def test_uninvoked_nested_helper_does_not_supply_a_callback_oracle(helper):
    source = _source(helper + " expect(real()).toBe(1);")
    assertion, = _assertions(source)
    assert assertion.left == "real()"
    gaps = javascript_coverage_gaps(source.encode(), parse_javascript(source.encode()),
                                    "tests/foundation.test.ts", "after")
    assert [gap.callee for gap in gaps] == ["expect(...).toBe"]


@pytest.mark.parametrize("helper", [
    "const unused = (): void => { expect(fake()).toBe(0); };",
    "const unused = async (): Promise<void> => { expect(fake()).toBe(0); };",
])
def test_typed_nested_arrow_does_not_supply_an_outer_callback_oracle(helper):
    source = _source(helper + " expect(real()).toBe(1);")
    assertion, = _assertions(source)
    assert assertion.left == "real()"
    gaps = javascript_coverage_gaps(source.encode(), parse_javascript(source.encode()),
                                    "tests/foundation.test.ts", "after")
    assert [gap.callee for gap in gaps] == ["expect(...).toBe"]


@pytest.mark.parametrize("callback", [
    "(): void => {{ {body} }}",
    "async (): Promise<void> => {{ {body} }}",
])
def test_typed_main_callback_retains_its_own_assertion(callback):
    source = _source("expect(real()).toBe(1);", callback=callback)
    unit, = parse_javascript(source.encode()).units
    assert [assertion.left for assertion in unit.side.assertions] == ["real()"]
    assert javascript_coverage_gaps(source.encode(), parse_javascript(source.encode()),
                                    "tests/foundation.test.ts", "after") == []


@pytest.mark.parametrize("subject", [
    'lookup("semi; and closing ) }")',
    "lookup('two  spaces')",
    "lookup(/[,);}]/, `comma, and ) brackets`)",
    "items.map((value, index) => ({ value, index }))",
    "(record(2, 3), total([2, 3]))",
    "total(/* comma, ); } */ [2, 3])",
])
def test_balanced_expect_arguments_keep_subject_and_complete_source(subject):
    call = f"expect({subject}).toBe(5)"
    source = _source(call + ";")
    assertion, = _assertions(source)
    assert assertion.left == subject
    assert assertion.text == call
    assert source[slice(*assertion.span)] == call
    assert assertion.right_literal == "5"
    assert assertion.right_value is not None


def test_nested_expect_calls_keep_both_complete_calls():
    source = _source("expect(doThing(expect(value).toBe(1))).toBe(2);")
    outer, inner = _assertions(source)
    assert outer.left == "doThing(expect(value).toBe(1))"
    assert inner.left == "value"
    assert outer.text == "expect(doThing(expect(value).toBe(1))).toBe(2)"
    assert inner.text == "expect(value).toBe(1)"
    assert (outer.right_literal, inner.right_literal) == ("2", "1")


@pytest.mark.parametrize("malformed", [
    "expect(value).toBe();",
    "expect(value).toBe(,);",
    "expect(value).toBe(1;",
    "expect(value).toBe([1});",
])
def test_malformed_matcher_cannot_consume_the_following_assertion(malformed):
    source = _source(malformed + " expect(real()).toBe(2);")
    assertion, = _assertions(source)
    assert assertion.left == "real()"
    assert assertion.text == "expect(real()).toBe(2)"


@pytest.mark.parametrize("call", [
    "expect(subject()).toBe({value})",
    "expect(subject()).toEqual({value})",
    "expect(subject()).toStrictEqual({value})",
    "assert.strictEqual(subject(), {value})",
    "t.assert.strictEqual(subject(), {value})",
])
@pytest.mark.parametrize("before_value,after_value", [
    ("42", "0"),
    ('"expected"', '"actual"'),
    ("true", "false"),
    ("null", '"null"'),
])
def test_literal_expected_rewrite_blocks_with_existing_policy(call, before_value, after_value):
    before = _source(call.format(value=before_value) + ";")
    after = _source(call.format(value=after_value) + ";")
    _ir, findings, verdict = _analyze(before, after)
    assert (verdict, [(f.rule, f.severity) for f in findings]) == (
        "block", [("EXPECTED_VALUE_CHANGED", "high")],
    )
    assert "NO_PROD_CHANGE_IN_DIFF" in findings[0].escalators


@pytest.mark.parametrize("before_value,after_value", [
    ("1", "1.0"),
    ("100", "1e2"),
    ('"answer"', "'answer'"),
    ('"a\\nb"', "'a\\nb'"),
    ('"a"', '"\\u0061"'),
])
def test_equivalent_scalar_spellings_are_preserving(before_value, after_value):
    before = _source(f"expect(subject()).toBe({before_value});")
    after = _source(f"expect(subject()).toBe({after_value});")
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


def test_object_is_matcher_keeps_the_difference_between_signed_zeroes():
    _ir, findings, verdict = _analyze(
        _source("expect(subject()).toBe(-0);"),
        _source("expect(subject()).toBe(0);"),
    )
    assert (verdict, [(f.rule, f.severity) for f in findings]) == (
        "block", [("EXPECTED_VALUE_CHANGED", "high")],
    )


@pytest.mark.parametrize("call", [
    "expect(subject()).toBe({value});",
    "assert.strictEqual(subject(), {value});",
])
def test_strict_scalar_expectations_do_not_confuse_boolean_and_number(call):
    _ir, findings, verdict = _analyze(
        _source(call.format(value="true")), _source(call.format(value="1")),
    )
    assert (verdict, [(f.rule, f.severity) for f in findings]) == (
        "block", [("EXPECTED_VALUE_CHANGED", "high")],
    )


@pytest.mark.parametrize("before,after", [
    ("expect(subject()).toBeTruthy();", "expect(subject()).toBe(5);"),
    ("expect(subject()).toBeDefined();", "expect(subject()).toEqual(5);"),
    ("assert.ok(subject());", "assert.strictEqual(subject(), 5);"),
    ("assert(subject());", "assert.deepStrictEqual(subject(), 5);"),
    ("t.assert.ok(subject());", "t.assert.deepEqual(subject(), 5);"),
])
def test_strengthening_without_an_old_expected_operand_stays_preserving(before, after):
    _ir, findings, verdict = _analyze(_source(before), _source(after))
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("imports,call", [
    ('import { expect as check } from "vitest";', "check(subject()).toBe({value});"),
    ('import * as jest from "@jest/globals";', "jest.expect(subject()).toBe({value});"),
    ('import { strictEqual as same } from "node:assert";', "same(subject(), {value});"),
    ('const { strictEqual: same } = require("node:assert");', "same(subject(), {value});"),
])
def test_import_aliases_keep_expected_value_detection(imports, call):
    before = _source(call.format(value="5"), imports)
    after = _source(call.format(value="0"), imports)
    _ir, findings, verdict = _analyze(before, after)
    assert (verdict, [(f.rule, f.severity) for f in findings]) == (
        "block", [("EXPECTED_VALUE_CHANGED", "high")],
    )


def test_inner_alias_shadow_does_not_supply_literal_evidence_or_hide_outer_binding():
    source = _source('''{
      const check = standin;
      check(fake()).toBe(0);
    }
    check(real()).toBe(5);''', 'import { expect as check } from "vitest";')
    assertion, = _assertions(source)
    assert assertion.left == "real()"
    assert assertion.right_literal == "5"
    gaps = javascript_coverage_gaps(source.encode(), parse_javascript(source.encode()),
                                    "tests/foundation.test.ts", "after")
    assert len(gaps) == 1
    assert "unresolved" in gaps[0].reason


@pytest.mark.parametrize("body", [
    "expect(subject()).toBe(factory());",
    "expect(subject()).toBe(expected);",
    "expect(subject()).toBe(expect.any(Number));",
    "expect(subject()).toEqual([1, 2]);",
    "expect(subject()).toEqual({ value: 1 });",
])
def test_non_scalar_expectations_do_not_claim_literal_values(body):
    assertion, = _assertions(_source(body))
    assert assertion.right_value is None


@pytest.mark.parametrize("method", ["equal", "deepEqual"])
def test_legacy_node_equality_does_not_claim_scalar_rewrite_semantics(method):
    before = _source(f"assert.{method}(subject(), 42);")
    after = _source(f"assert.{method}(subject(), 0);")
    assert _assertions(before)[0].right_value is None
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("before,after", [
    ("expect(subject()).toBe(42 /* explanation */);", "expect(subject()).toBe(42);"),
    ("assert.strictEqual(subject(), /* explanation */ 42);", "assert.strictEqual(subject(), 42);"),
    ("expect(subject()).toBeCloseTo(1.23, /* explanation */);", "expect(subject()).toBeCloseTo(1.23);"),
])
def test_comments_around_scalar_arguments_preserve_expectations(before, after):
    _ir, findings, verdict = _analyze(_source(before), _source(after))
    assert (findings, verdict) == ([], "pass")


def test_comment_spelling_inside_a_literal_remains_string_data():
    assertion, = _assertions(_source('expect(subject()).toBe("/* explanation */");'))
    assert assertion.right_literal == '"/* explanation */"'
    assert assertion.right_value == repr("/* explanation */")


@pytest.mark.parametrize("before_precision,after_precision,expected", [
    (", 5", ", 2", [("TOLERANCE_LOOSENED", "high")]),
    (", 5", "", [("TOLERANCE_LOOSENED", "high")]),
    ("", ", 1", [("TOLERANCE_LOOSENED", "high")]),
    (", 2", ", 5", []),
    ("", ", 2", []),
    (", 2", "", []),
])
def test_positive_precision_uses_digits_and_the_default(before_precision, after_precision, expected):
    before = _source(f"expect(subject()).toBeCloseTo(5{before_precision});")
    after = _source(f"expect(subject()).toBeCloseTo(5{after_precision});")
    _ir, findings, verdict = _analyze(before, after)
    assert [(f.rule, f.severity) for f in findings] == expected
    assert verdict == ("block" if expected else "pass")


def test_default_precision_is_in_ir_without_an_explicit_second_argument():
    assertion, = _assertions(_source("expect(subject()).toBeCloseTo(5);"))
    assert assertion.epsilon == "2"
    assert assertion.epsilon_kind == "places"
    assert assertion.right_literal == "5"


@pytest.mark.parametrize("precision", ["2", "5", "digits", "2.5", "Infinity"])
def test_negated_precision_does_not_claim_positive_tolerance_direction(precision):
    assertion, = _assertions(_source(f"expect(subject()).not.toBeCloseTo(5, {precision});"))
    assert assertion.positive is False
    assert assertion.epsilon is None


@pytest.mark.parametrize("precision", ["digits", "2.5", "Infinity", "NaN"])
def test_unknown_precision_is_not_given_a_numeric_tolerance(precision):
    assertion, = _assertions(_source(f"expect(subject()).toBeCloseTo(5, {precision});"))
    assert assertion.epsilon is None


def test_assertion_reordering_and_node_message_edits_stay_preserving():
    before = _source('expect(first()).toBe(1); assert.strictEqual(second(), 2, "before");')
    after = _source('assert.strictEqual(second(), 2, "after"); expect(first()).toBe(1);')
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


def test_import_alias_rename_keeps_the_same_oracle():
    before = _source("check(subject()).toBe(5);", 'import { expect as check } from "vitest";')
    after = _source("verify(subject()).toBe(5);", 'import { expect as verify } from "vitest";')
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


def test_reordering_sibling_tests_with_duplicate_names_keeps_their_oracles():
    one = 'describe("first", () => { test("same", () => { expect(first()).toBe(1); }); });'
    two = 'describe("second", () => { test("same", () => { expect(second()).toBe(2); }); });'
    _ir, findings, verdict = _analyze(one + "\n" + two, two + "\n" + one)
    assert (findings, verdict) == ([], "pass")


_CONTRACT_TOOLS = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/assertion_contract.py"))
_MUTATIONS = _CONTRACT_TOOLS["foundation_mutation_cases"]()


@pytest.mark.parametrize("case", _MUTATIONS, ids=lambda case: case["id"])
def test_independent_foundation_mutations(case):
    _CONTRACT_TOOLS["check_mutation_case"](case)


_FOUNDATION_CONTRACT = json.loads(
    (Path(__file__).parent / "data/javascript_foundation_mutations.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("field,value,message", [
    ("path", "../outside.test.js", "unsafe or non-test path"),
    ("before", "", "before source is required"),
    ("kind", "unknown", "invalid mutation kind"),
    ("verdict", "pass", "outcome contradicts mutation kind"),
    ("rule", "ASSERT_REMOVED", "outcome contradicts mutation kind"),
    ("severity", "warn", "outcome contradicts mutation kind"),
])
def test_foundation_inventory_rejects_invalid_or_contradictory_records(field, value, message):
    contract = copy.deepcopy(_FOUNDATION_CONTRACT)
    contract["mutations"][0][field] = value
    with pytest.raises(ValueError, match=message):
        _CONTRACT_TOOLS["validate_foundation_contract"](contract)


def test_foundation_inventory_rejects_duplicate_ids():
    contract = copy.deepcopy(_FOUNDATION_CONTRACT)
    contract["mutations"].append(copy.deepcopy(contract["mutations"][0]))
    with pytest.raises(ValueError, match="duplicate mutations id"):
        _CONTRACT_TOOLS["validate_foundation_contract"](contract)


def test_foundation_inventory_rejects_an_implicit_outcome():
    contract = copy.deepcopy(_FOUNDATION_CONTRACT)
    del contract["mutations"][0]["severity"]
    with pytest.raises(ValueError, match="outcome fields must be explicit"):
        _CONTRACT_TOOLS["validate_foundation_contract"](contract)
