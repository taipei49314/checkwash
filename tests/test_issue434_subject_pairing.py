"""The order fallback pairs by subject first, and `match=` added is no removal (#434).

Ruling of 2026-10-16 (「全部照建議」, "all as recommended"):

- A: in the order fallback, an old assertion first takes a leftover that
  checks the same subject, written out or through one plain single-target
  local binding resolved at that assertion. Among those, the same form comes
  first, then at least the old strength, then span order; with none, the old
  rule applies. Python only, own assertions only. The subject test is one
  helper under `ir/` (`ir.subjects`), for #460 to reuse.
- B: a removed bare `pytest.raises(E)` pairs with an unused
  `pytest.raises(E, match=...)` of the same callee, expected types and other
  keywords, in a pass after the order fallback. Where the bare call is still
  removed (`raises_match_fold_neg`), ASSERT_REMOVED says the raise is still
  checked. The call reader is `ir.astutil.raises_call`, for #423 to reuse.

The `.gwcase` fixtures `subject_pairing_*` and `raises_match_*` carry the
end-to-end shapes, #457's known limit among them.
"""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.astutil import raises_call, same_raises_check
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import Assertion
from checkwash.ir.subjects import reaching_signature, same_subject, subject_of


# --- B: the raises-call reader ------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("pytest.raises(ValueError)", ("pytest.raises", frozenset({"ValueError"}), (), False)),
    ('pytest.raises(ValueError, match="must be absolute")',
     ("pytest.raises", frozenset({"ValueError"}), (), True)),
    ("pytest.warns(UserWarning, match='old')", ("pytest.warns", frozenset({"UserWarning"}), (), True)),
    ("raises((KeyError, errors.Missing))", ("raises", frozenset({"KeyError", "errors.Missing"}), (), False)),
    ("pytest.raises(ValueError, check=is_bad, match='x')",
     ("pytest.raises", frozenset({"ValueError"}), (("check", "is_bad"),), True)),
    ("pytest.raises(error_type())", ("pytest.raises", None, (), False)),
], ids=["bare", "match", "warns", "tuple_of_types", "other_keyword", "unreadable_type"])
def test_the_raises_reader_reads_callee_types_and_keywords(text, expected):
    assert raises_call(text) == expected


@pytest.mark.parametrize("text", [
    "pytest.raises(ValueError, parse, '')",
    "pytest.raises(*errors)",
    "pytest.raises(ValueError, **options)",
    "pytest.raises()",
    "self.assertRaises(ValueError)",
    "pytest.fail('no')",
    "ValueError",
    "pytest.raises(",
    "",
    None,
], ids=["call_form", "starred", "double_starred", "no_type", "unittest", "other_call", "not_a_call",
        "unparseable", "empty", "none"])
def test_only_the_context_manager_form_is_read(text):
    assert raises_call(text) is None


@pytest.mark.parametrize("bare, matched, same", [
    ("pytest.raises(ValueError)", 'pytest.raises(ValueError, match="must be absolute")', True),
    ("pytest.raises((TypeError, ValueError))", "pytest.raises((ValueError, TypeError), match='x')", True),
    ("raises(ValueError)", "raises(ValueError, match='x')", True),
    ("pytest.raises(ValueError)", "pytest.raises(Exception, match='x')", False),
    ("pytest.warns(UserWarning)", "pytest.raises(UserWarning, match='x')", False),
    ("pytest.raises(ValueError, check=ok)", "pytest.raises(ValueError, match='x')", False),
    ("pytest.raises(ValueError, match='a')", "pytest.raises(ValueError, match='b')", False),
    ("pytest.raises(ValueError)", "pytest.raises(ValueError)", False),
    ("pytest.raises(error_type())", "pytest.raises(error_type(), match='x')", False),
], ids=["match_added", "types_reordered", "bare_name", "type_changed", "callee_changed",
        "keyword_dropped", "match_rewritten", "no_match", "unreadable_type"])
def test_only_a_match_added_and_nothing_else_is_the_same_check(bare, matched, same):
    assert same_raises_check(bare, matched) is same


# --- A: the subject a bare local name stands for ------------------------------------

HEAD = "from app.geometry import area\n\n\n"


def _last(source):
    unit = parse_python((HEAD + source).encode(), collect_tests=True).units[0]
    return unit.side.assertions[-1]


@pytest.mark.parametrize("source, expected", [
    ("def test_area():\n    result = area(4, 5)\n    assert result == 20.0\n", ("area(4, 5)", "")),
    ("def test_area():\n    width = 4\n    result = area(width, 5)\n    assert result == 20.0\n",
     ("area(width, 5)", "width\x1d4")),
    ("def test_area(fast):\n    if fast:\n        result = area(4, 5)\n    assert result == 20.0\n",
     ("area(4, 5)", "")),
    ("def test_area():\n    result = area(4, 5)\n    result = 20.0\n    assert result == 20.0\n", ("20.0", "")),
    ("def test_area():\n    result = area(4, 5)\n    assert result is not None\n", ("area(4, 5)", "")),
], ids=["plain", "context_of_its_names", "single_conditional_binding", "the_binding_that_reaches", "non_null"])
def test_a_plain_local_name_stands_for_the_expression_it_was_bound_to(source, expected):
    assert _last(source).resolved_subject == expected


def test_a_unittest_operand_resolves_too():
    source = (
        "import unittest\n\n" + HEAD
        + "class TestArea(unittest.TestCase):\n"
        "    def test_area(self):\n"
        "        result = area(4, 5)\n"
        "        self.assertEqual(result, 20.0)\n"
    )
    unit = parse_python(source.encode(), collect_tests=True).units[0]
    assert unit.qualname == "TestArea.test_area"
    assert unit.side.assertions[-1].resolved_subject == ("area(4, 5)", "")


@pytest.mark.parametrize("source", [
    "def test_area(result):\n    result = area(4, 5)\n    assert result == 20.0\n",
    "def test_area():\n    global result\n    result = area(4, 5)\n    assert result == 20.0\n",
    ("def test_area():\n    result = area(4, 5)\n\n    def reset():\n        nonlocal result\n"
     "        result = 20.0\n\n    reset()\n    assert result == 20.0\n"),
    "def test_area():\n    result = area(4, 5)\n    result += 0\n    assert result == 20.0\n",
    "def test_area():\n    result: float = area(4, 5)\n    assert result == 20.0\n",
    "def test_area():\n    result, unit = area(4, 5), 'cm2'\n    assert result == 20.0\n",
    "def test_area():\n    result = expected = area(4, 5)\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    for result in [20.0]:\n        pass\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    with measure() as result:\n        pass\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    print(result := 20.0)\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    del result\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    from app.values import result\n    assert result == 20.0\n",
    ("def test_area():\n    result = area(4, 5)\n    try:\n        pass\n    except ValueError as result:\n"
     "        pass\n    assert result == 20.0\n"),
    ("def test_area():\n    result = area(4, 5)\n\n    def result():\n        return 20.0\n\n"
     "    assert result == 20.0\n"),
    ("def test_area():\n    result = area(4, 5)\n\n    def other():\n        result = 0\n        return result\n\n"
     "    assert result == 20.0\n"),
    "def test_area(fast):\n    result = area(4, 5)\n    if fast:\n        result = 20.0\n    assert result == 20.0\n",
    ("def test_area(cases):\n    result = area(4, 5)\n    for case in cases:\n        assert result == 20.0\n"
     "        result = area(*case)\n"),
    "def test_area():\n    result = area(4, 5)\n\n    def check():\n        assert result == 20.0\n\n    check()\n",
    "def test_area():\n    assert result == 20.0\n",
    "def test_area():\n    result = area(4, 5)\n    assert result.real == 20.0\n",
], ids=["parameter", "global", "nonlocal", "augmented", "annotated", "tuple", "chained", "for_target",
        "with_target", "walrus", "deleted", "imported", "except_target", "def", "nested_plain_binding",
        "two_bindings_reach", "conditional_binding_after", "nested_scope_assertion", "unbound",
        "not_a_bare_name"])
def test_any_other_binding_or_scope_leaves_the_name_unresolved(source):
    assert _last(source).resolved_subject is None


# --- A: the subject test ------------------------------------------------------------

def _record(**fields):
    return Assertion(id="a0", form="compare_eq", strength=90, text="assert x == 1", span=(0, 1), **fields)


def test_the_reaching_signature_is_sorted_and_skips_names_the_unit_never_binds():
    assert reaching_signature({"b": "2", "a": "1"}, ["b", "a", "c", "a"]) == "a\x1d1\x1eb\x1d2"
    assert reaching_signature({}, ["area"]) == ""


def test_a_subject_is_read_from_the_record():
    written = _record(left="total(items)", left_names=("items", "total"), reaching={"items": "[1, 2]"})
    assert subject_of(written) == ("total(items)", "items\x1d[1, 2]")
    # A JSON round trip turns the tuple into a list.
    resolved = _record(left="result", resolved_subject=["area(4, 5)", ""])
    assert subject_of(resolved) == ("area(4, 5)", "")
    assert subject_of(_record()) is None
    assert subject_of(_record(left="x", inherited=True)) is None
    assert subject_of(_record(left="x", via="TotalTest._check")) is None


def _unit_assertions(source):
    return parse_python((HEAD + source).encode(), collect_tests=True).units[0].side.assertions


@pytest.mark.parametrize("old, new, same", [
    ("def test_area():\n    assert area(4, 5) == 20.0\n",
     "def test_area():\n    result = area(4, 5)\n    assert result == 20.0\n", True),
    ("def test_area():\n    result = area(4, 5)\n    assert result == 20.0\n",
     "def test_area():\n    assert area(4,5) > 0\n", True),
    ("def test_area():\n    items = [1, 2]\n    assert area(*items) == 2\n",
     "def test_area():\n    items = [1, 2]\n    assert area(*items) > 0\n", True),
    ("def test_area():\n    items = [1, 2]\n    assert area(*items) == 2\n",
     "def test_area():\n    items = [1, 3]\n    assert area(*items) > 0\n", False),
    ("def test_area():\n    assert area(4, 5) == 20.0\n",
     "def test_area():\n    assert area(5, 4) == 20.0\n", False),
    ("def test_area():\n    assert area(4, 5) == 20.0\n",
     "def test_area():\n    result = area(4, 5)\n    assert isinstance(result, float)\n", False),
], ids=["resolved_after", "resolved_before", "same_context", "context_changed", "other_expression",
        "no_subject"])
def test_two_assertions_check_the_same_subject_in_the_same_context(old, new, same):
    assert same_subject(_unit_assertions(old)[-1], _unit_assertions(new)[-1]) is same


# --- the pairing ----------------------------------------------------------------------

def _delta(before, after):
    old = parse_python(before.encode(), collect_tests=True)
    new = parse_python(after.encode(), collect_tests=True)
    unit = align_file("tests/test_geometry.py", "test", "modified", old, new).units[0]
    pairs = [(p.before_id, p.after_id, p.strength_change, p.fallback) for p in unit.delta.assertion_pairs]
    return pairs, unit.delta.assertions_removed, unit.delta.assertions_added


OLD = HEAD + "def test_area():\n    assert area(4, 5) == 20.0\n"


@pytest.mark.parametrize("after, pairs, added", [
    ("def test_area():\n    result = area(4, 5)\n    assert isinstance(result, float)\n    assert result == 20.0\n",
     [("a0", "a1", 0, True)], ["a0"]),
    ("def test_area():\n    result = area(4, 5)\n    assert result == 20.0\n    assert isinstance(result, float)\n",
     [("a0", "a0", 0, True)], ["a1"]),
    ("def test_area():\n    result = area(4, 5)\n    assert result is not None\n    assert result == 20.0\n",
     [("a0", "a1", 0, True)], ["a0"]),
    ("def test_area():\n    result = area(4, 5)\n    assert isinstance(result, float)\n    assert result is not None\n",
     [("a0", "a1", -60, True)], ["a0"]),
    ("def test_area(result, exact):\n    if exact:\n        result = area(4, 5)\n"
     "    assert result is not None\n    assert result == 20.0\n",
     [("a0", "a0", -60, True)], ["a1"]),
    ("def test_area():\n    result = area(4, 5)\n    assert result is not None\n    result = 20.0\n"
     "    assert result == 20.0\n",
     [("a0", "a0", -60, True)], ["a1"]),
], ids=["precondition_before", "precondition_after", "not_none_precondition", "control", "parameter",
        "rebound"])
def test_the_fallback_gives_the_old_assertion_a_leftover_on_its_subject_first(after, pairs, added):
    assert _delta(OLD, HEAD + after) == (pairs, [], added)


def test_a_decoy_of_the_old_expectation_on_another_subject_does_not_take_the_place():
    before = "from app.billing import subtotal, total\n\n\ndef test_total():\n    items = [10.5, 94.8]\n"
    old = before + "    assert total(items) == 105.3\n"
    for decoy_first in (False, True):
        lines = ["    assert total(items) > 0\n", "    assert subtotal(items) == 105.3\n"]
        if decoy_first:
            lines.reverse()
        weakened = "a1" if decoy_first else "a0"
        decoy = "a0" if decoy_first else "a1"
        assert _delta(old, before + "".join(lines)) == ([("a0", weakened, -50, True)], [], [decoy])


RAISES = "import pytest\n\nfrom app import create\n\n\ndef test_relative_path_rejected():\n"


def test_a_match_added_to_a_bare_raises_pairs_after_the_fallback():
    before = RAISES + "    with pytest.raises(ValueError):\n        create('relative/path')\n"
    after = RAISES + "    with pytest.raises(ValueError, match='must be absolute'):\n        create('relative/path')\n"
    assert _delta(before, after) == ([("a0", "a0", None, False)], [], [])
    # The reverse is no pair.
    assert _delta(after, before) == ([], ["a0"], ["a0"])


def test_an_excinfo_assert_folded_into_match_keeps_the_bare_call_removed():
    before = (RAISES + "    with pytest.raises(ValueError) as excinfo:\n        create('relative/path')\n"
              "    assert 'must be absolute' in str(excinfo.value)\n")
    after = RAISES + "    with pytest.raises(ValueError, match='must be absolute'):\n        create('relative/path')\n"
    assert _delta(before, after) == ([("a1", "a0", 0, True)], ["a0"], [])


# --- end to end ---------------------------------------------------------------------

def _outcome(before, after, path="tests/test_paths.py"):
    _ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 19),
    )
    return verdict, findings


def test_the_fold_shape_says_the_raise_is_still_checked():
    before = (RAISES + "    with pytest.raises(ValueError) as excinfo:\n        create('relative/path')\n"
              "    assert 'must be absolute' in str(excinfo.value)\n")
    after = RAISES + '    with pytest.raises(ValueError, match="must be absolute"):\n        create(\'relative/path\')\n'
    verdict, findings = _outcome(before, after)
    assert verdict == "pass"
    assert [(f.rule, f.severity, f.deescalators) for f in findings] == [
        ("ASSERT_REMOVED", "warn", ["SAME_UNIT_REWRITE"])]
    assert findings[0].message == (
        "test_relative_path_rejected: assertion removed (strength UNKNOWN); the raise is still "
        'checked by pytest.raises(ValueError, match="must be absolute")')


def test_another_expected_type_keeps_the_plain_removal_message():
    before = RAISES + "    with pytest.raises(ValueError):\n        create('relative/path')\n"
    after = RAISES + "    with pytest.raises(Exception, match='must be absolute'):\n        create('relative/path')\n"
    verdict, findings = _outcome(before, after)
    assert verdict == "pass"
    assert [f.message for f in findings] == ["test_relative_path_rejected: assertion removed (strength UNKNOWN)"]


def test_a1_passes_and_its_control_still_blocks():
    before = OLD
    precondition = HEAD + (
        "def test_area():\n    result = area(4, 5)\n    assert isinstance(result, float)\n    assert result == 20.0\n")
    assert _outcome(before, precondition, "tests/test_geometry.py") == ("pass", [])
    control = precondition.replace("assert result == 20.0", "assert result is not None")
    verdict, findings = _outcome(before, control, "tests/test_geometry.py")
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert "subject and polarity both changed" in findings[0].message
