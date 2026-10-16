"""unittest operands and `pytest.approx(expected=)` are read by name as well as by position (#462).

The unittest reader took an assertion's operands from the call's positional
arguments only. `self.assertEqual(first=value(), second=[1, 2])` recorded no
subject, no expected value and no operand-derived strength, and was trivial:
rewriting its expectation passed with zero findings, and respelling a
container-literal assertion with keywords blocked as a weakening.
`pytest.approx(expected=105.0)` recorded no expected value either. Ruling of
2026-10-16 (「全部照建議」):

1. Scope (b): unittest assertion methods and `pytest.approx(expected=)`, as
   one family, Python assertion operands bound by name.
2. Operands that cannot be bound (b): `self.assertEqual(**case)` and
   `self.assertEqual(*pair)` record no operand and are not trivial. A known
   oracle replaced by one is ASSERT_WEAKENED "cannot verify", never mild;
   unknown to unknown stays silent.

The `.gwcase` fixtures `unittest_keyword_*`, `unittest_unbound_*` and
`approx_expected_keyword_*` carry the end-to-end shapes.
"""

import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import (
    _UNITTEST_MAP,
    _UNITTEST_OPERANDS,
    _Offsets,
    _classify_assert_expr,
    _classify_unittest_call,
    _unittest_operands,
    parse_python,
)


def _call(src):
    return ast.parse(src).body[0].value


def _classified(src):
    return _classify_unittest_call(_call(src), _Offsets(src))


# --- the binding helper -------------------------------------------------------------

def test_the_name_table_covers_every_method_but_the_raises_family():
    raises = {method for method, (form, _strength) in _UNITTEST_MAP.items() if form == "raises"}
    assert raises == {"assertRaises", "assertRaisesRegex", "assertWarns", "assertWarnsRegex"}
    assert set(_UNITTEST_OPERANDS) == set(_UNITTEST_MAP) - raises


@pytest.mark.parametrize("src", [
    "self.assertEqual(value(), [1, 2])",
    "self.assertEqual(value(), [1, 2], 'message')",
    "self.assertEqual(value(), [1, 2], msg='message')",
    "self.assertAlmostEqual(total(), 78.75, 2)",
    "self.assertEqual(value(), [1, 2], *rest)",
    "self.assertEqual(value())",
    "self.assertTrue(ok)",
    "self.assertRaises(ValueError, parse, '')",
    "self.assertRaises(*errors)",
], ids=["two", "message", "message_keyword", "places", "starred_after", "missing_operand", "one",
        "raises", "raises_starred"])
def test_operands_stated_by_position_are_the_call_arguments(src):
    # The same nodes, so every record of such a call is what it was.
    call = _call(src)
    operands = _unittest_operands(call.func.attr, call)
    assert len(operands) == len(call.args)
    assert all(mine is theirs for mine, theirs in zip(operands, call.args))


@pytest.mark.parametrize("method", sorted(_UNITTEST_OPERANDS))
def test_each_operand_binds_by_its_unittest_parameter_name(method):
    names = _UNITTEST_OPERANDS[method]
    values = ("subject()", "expected()")[:len(names)]
    # Written in reverse, so the keywords' order is not what binds them.
    keywords = ", ".join(f"{name}={value}" for name, value in reversed(list(zip(names, values))))
    call = _call(f"self.{method}({keywords})")
    assert [ast.unparse(node) for node in _unittest_operands(method, call)] == list(values)


@pytest.mark.parametrize("src", [
    "self.assertEqual(value(), *rest, second=[1, 2])",
    "self.assertEqual(first=value(), second=[1, 2], **extra)",
], ids=["keyword_after_starred", "spread_beside_keywords"])
def test_a_keyword_operand_is_read_beside_a_spread(src):
    # No operand is read from a position at or after a starred argument; its
    # keyword is, as for a tolerance call (#222).
    c = _classified(src)
    assert c.unbound_operands is False
    assert (c.left, c.right_value, c.strength) == ("value()", "[1, 2]", 100)


# --- keyword and positional spellings record the same assertion ---------------------

SAME_RECORD = [
    ("self.assertEqual(value(), [1, 2])", "self.assertEqual(first=value(), second=[1, 2])"),
    ("self.assertEqual(value(), [1, 2])", "self.assertEqual(value(), second=[1, 2])"),
    ("self.assertEqual(105.0, total())", "self.assertEqual(first=105.0, second=total())"),
    ("self.assertEqual(len(rows), 3)", "self.assertEqual(first=len(rows), second=3)"),
    ("self.assertEqual(total(), total())", "self.assertEqual(first=total(), second=total())"),
    ("self.assertIs(result, None)", "self.assertIs(expr1=result, expr2=None)"),
    ("self.assertIsNot(None, result)", "self.assertIsNot(expr2=result, expr1=None)"),
    ("self.assertTrue(True)", "self.assertTrue(expr=True)"),
    ("self.assertTrue(abs(total() - 78.75) < 0.01)", "self.assertTrue(expr=abs(total() - 78.75) < 0.01)"),
    ("self.assertLess(abs(total() - 78.75), 0.01)", "self.assertLess(a=abs(total() - 78.75), b=0.01)"),
    ("self.assertGreater(0.01, abs(total() - 78.75))", "self.assertGreater(b=abs(total() - 78.75), a=0.01)"),
    ("self.assertLess(total(), 80)", "self.assertLess(a=total(), b=80)"),
    ("self.assertGreater(80, total())", "self.assertGreater(a=80, b=total())"),
    ("self.assertAlmostEqual(total(), 78.75, places=2)",
     "self.assertAlmostEqual(first=total(), second=78.75, places=2)"),
    ("self.assertAlmostEqual(total(), 78.75)", "self.assertAlmostEqual(second=78.75, first=total())"),
    ("self.assertIn('ok', status())", "self.assertIn(member='ok', container=status())"),
    ("self.assertRegex(message(), 'total')", "self.assertRegex(text=message(), expected_regex='total')"),
    ("self.assertNotRegex(message(), 'error')", "self.assertNotRegex(text=message(), unexpected_regex='error')"),
    ("self.assertIsInstance(result, dict)", "self.assertIsInstance(obj=result, cls=dict)"),
    ("self.assertIsNone(find())", "self.assertIsNone(obj=find())"),
    ("self.assertListEqual(items(), [1])", "self.assertListEqual(list1=items(), list2=[1])"),
    ("self.assertDictEqual(config(), {'a': 1})", "self.assertDictEqual(d1=config(), d2={'a': 1})"),
]


@pytest.mark.parametrize("positional, keyword", SAME_RECORD, ids=[
    "container_struct", "mixed", "literal_first_flip", "len_shape", "self_comparison", "is_none",
    "is_not_none_literal_first", "true_literal", "true_hand_rolled", "less_hand_rolled", "greater_hand_rolled",
    "less_bound_key", "greater_bound_key_reversed", "places_keyword", "default_places", "membership",
    "regex", "not_regex", "isinstance", "is_none_method", "list_equal", "dict_equal",
])
def test_the_keyword_spelling_records_what_the_positional_one_records(positional, keyword):
    # Every rule that reads an operand sees the keyword spelling: the
    # container upgrade, the literal-side flip, the len() shape rule, the
    # tautology checks, assertIs(x, None), the hand-rolled bounds, the bound
    # keys and the tolerances.
    by_name = _classified(keyword)
    assert by_name.left is not None
    assert by_name == _classified(positional)


def test_a_bound_key_is_read_from_the_bound_first_operand():
    # `_unittest_bound` compared the subject with `node.args[0]`, which a
    # keyword-only call does not have.
    c = _classified("self.assertGreater(a=80, b=total())")
    assert (c.left, c.predicate, c.operand_source) == ("total()", "lt", "80")


@pytest.mark.parametrize("src, trivial", [
    ("self.assertEqual(first=str(1), second='1')", True),
    ("self.assertEqual(first=total(), second=78.75)", False),
    ("self.assertEqual(**case)", False),
], ids=["builtin_padding", "real_oracle", "unbound"])
def test_triviality_is_read_from_the_bound_operands(src, trivial):
    # A keyword-only call was trivial whatever it compared, so it never
    # counted as oracle mass for SAME_UNIT_REWRITE, SPLIT_OR_RENAMED or
    # RESTRUCTURED; an unbound one compares something unknown, not nothing.
    assert _classified(src).trivial is trivial


# --- operands that cannot be bound (462.Q2) -----------------------------------------

@pytest.mark.parametrize("src", [
    "self.assertEqual(**case)",
    "self.assertEqual(*pair)",
    "self.assertEqual(value(), **rest)",
    "self.assertEqual(value(), *rest)",
    "self.assertEqual(*pair, msg='totals')",
    "self.assertTrue(*flags)",
    "self.assertIsNone(**kw)",
    "self.assertIs(*pair)",
], ids=["kwargs", "args", "second_in_kwargs", "second_in_args", "args_with_message", "true", "is_none",
        "is_without_conversion"])
def test_operands_through_a_spread_are_unbound(src):
    call = _call(src)
    assert _unittest_operands(call.func.attr, call) is None
    c = _classified(src)
    assert c.unbound_operands is True
    assert c.trivial is False
    assert (c.form, c.strength) == _UNITTEST_MAP[call.func.attr]
    assert (c.left, c.right_literal, c.right_value) == (None, None, None)
    assert (c.left_names, c.right_names) == ((), ())
    assert (c.predicate, c.operand_source, c.unevaluated_expected) == (None, None, None)


@pytest.mark.parametrize("src, tolerance", [
    ("self.assertAlmostEqual(**case)", (None, None)),
    ("self.assertAlmostEqual(*pair, delta=0.5)", ("0.5", "delta")),
    ("self.assertAlmostEqual(*pair, places=3)", ("3", "places")),
    ("self.assertNotAlmostEqual(*pair, delta=0.5)", (None, None)),
], ids=["spread_may_carry_it", "delta_keyword", "places_keyword", "negated"])
def test_an_unbound_call_keeps_only_the_tolerance_it_states(src, tolerance):
    # The default places=7 is not assumed: the spread may carry places or
    # delta. A negated call records none, as it always has (#284).
    c = _classified(src)
    assert (c.epsilon, c.epsilon_kind) == tolerance


def _last_assertion(*lines):
    source = ("import unittest\n\nfrom app.billing import total\n\n\nclass TestTotal(unittest.TestCase):\n"
              "    def test_total(self):\n" + "".join(f"        {line}\n" for line in lines))
    units = parse_python(source.encode(), collect_tests=True).units
    return [a for unit in units for a in unit.side.assertions][-1]


def test_the_unbound_marker_reaches_the_ir():
    unbound = _last_assertion("case = {'first': total(), 'second': 78.75}", "self.assertEqual(**case)")
    assert unbound.text == "self.assertEqual(**case)"
    assert unbound.unbound_operands is True
    assert unbound.trivial is False
    assert (unbound.left, unbound.right_value, unbound.right_depends_on) == (None, None, ())
    bound = _last_assertion("self.assertEqual(first=total(), second=78.75)")
    assert bound.unbound_operands is False
    assert (bound.left, bound.right_value, bound.trivial) == ("total()", "78.75", False)


# --- pytest.approx(expected=) -------------------------------------------------------

@pytest.mark.parametrize("expr, expected, epsilon", [
    ("total() == pytest.approx(expected=105.0)", "105.0", "rel=1e-06"),
    ("total() == pytest.approx(105.0)", "105.0", "rel=1e-06"),
    ("total() == approx(expected=105.0, abs=0.5)", "105.0", "abs=0.5"),
    ("total() == pytest.approx(*values)", None, "rel=1e-06"),
], ids=["keyword", "positional", "keyword_with_tolerance", "starred"])
def test_approx_reads_its_expected_value_by_name_too(expr, expected, epsilon):
    src = f"assert {expr}"
    c = _classify_assert_expr(ast.parse(src).body[0].test, _Offsets(src))
    assert c.form == "approx"
    assert (c.right_literal, c.right_value, c.epsilon) == (expected, expected, epsilon)


# --- ASSERT_WEAKENED: a known oracle replaced by unbound operands -------------------

TEST = "tests/test_billing.py"
HEAD = "import unittest\n\nfrom app.billing import total, value\n\n\n"


def ut(*lines):
    return HEAD + "class TestTotal(unittest.TestCase):\n    def test_total(self):\n" + "".join(
        f"        {line}\n" for line in lines)


def outcome(before, after):
    _ir, findings, verdict = analyze(
        [FileChange(TEST, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 17),
    )
    return verdict, findings


@pytest.mark.parametrize("before, after", [
    (ut("self.assertEqual(total(), 78.75)"), ut("case = {'first': total(), 'second': 78.75}", "self.assertEqual(**case)")),
    (ut("self.assertEqual(value(), [1, 2])"), ut("pair = (value(), [1, 2])", "self.assertEqual(*pair)")),
    (ut("self.assertAlmostEqual(total(), 78.75, places=2)"), ut("self.assertAlmostEqual(**case)")),
    (ut("self.assertTrue(total())"), ut("self.assertTrue(*flags)")),
], ids=["kwargs", "args_from_container", "approx", "truthy"])
def test_a_known_oracle_replaced_by_unbound_operands_cannot_be_verified(before, after):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    finding = findings[0]
    assert "cannot verify the replacement is equivalent" in finding.message
    assert "which it cannot bind" in finding.message
    # Never mild: MILD_WEAKENING needs a drop under 30.
    assert finding.strength_drop == 999
    assert "MILD_WEAKENING" not in finding.deescalators


@pytest.mark.parametrize("before, after", [
    (ut("pair = (total(), 78.75)", "self.assertEqual(*pair)"),
     ut("case = {'first': total(), 'second': 78.75}", "self.assertEqual(**case)")),
    (ut("self.assertEqual(*pair)"), ut("self.assertEqual(*pair, msg='total')")),
    (ut("self.assertTrue(True)"), ut("self.assertTrue(*flags)")),
    (ut("self.assertEqual(first=str(1), second='1')"), ut("self.assertEqual(**case)")),
], ids=["unknown_to_unknown", "message_added", "tautology_is_no_oracle", "padding_is_no_oracle"])
def test_no_known_oracle_lost_is_no_finding(before, after):
    assert outcome(before, after) == ("pass", [])
