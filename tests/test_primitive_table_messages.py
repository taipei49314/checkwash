"""Literal container diagnostics do not hide changed concrete row answers."""

import pytest

from test_issue_expectation_families import run


BEFORE = ("from app.prod import pair_sum\n"
          "def test_first():\n    assert pair_sum([1, 2], [3, 4]) == [4, 6]\n"
          "def test_second():\n    assert pair_sum([0, 5], [1, 1]) == [1, 6]\n")
PRODUCTION = "def pair_sum(a, b):\n    return [x - y for x, y in zip(a, b)]\n"
AFTER = ("import pytest\nfrom app.prod import pair_sum\n"
         "@pytest.mark.parametrize('a,b,expected', [([1,2],[3,4],[4,6]), ([0,5],[1,1],[1,6])])\n"
         "def test_pairs(a,b,expected):\n    result = pair_sum(a,b)\n"
         "    assert result == expected, f'Expected {expected}, got {result} for {a} and {b}'\n")


def test_primitive_list_diagnostic_consolidation_preserves_answers():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]


def test_primitive_list_diagnostic_cannot_launder_buggy_answers():
    after = AFTER.replace("[4,6]", "[-2,-2]").replace("[1,6]", "[-1,4]")
    _, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == "block"
    assert sum(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings) == 2


@pytest.mark.parametrize("body", [
    "return [x + y for x, y in zip(a, b)]",
    "return [x + 1 for x in a if x > 0]",
    "return (min(a), max(b))",
    "return len(a) + len(b)",
])
def test_only_closed_primitive_production_can_format_result(body):
    ir, _, _ = run(BEFORE, AFTER, "def pair_sum(a, b):\n    " + body + "\n")
    assert any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("production", [
    "class Value:\n    def __format__(self, spec):\n        mutate()\ndef pair_sum(a,b):\n    return Value()\n",
    "from elsewhere import pair_sum\n",
    "def zip(a,b):\n    return []\ndef pair_sum(a,b):\n    return [x-y for x,y in zip(a,b)]\n",
    "def pair_sum(a,b):\n    a.append(custom())\n    return a\n",
    "def pair_sum(a,b):\n    return [custom(x) for x in a]\n",
    "def pair_sum(a,b):\n    return [x for row in a for x in row]\n",
])
def test_unknown_return_objects_and_side_effects_get_no_projection(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("message", ["f'{result.__class__}'", "f'{format_result(result)}'", "f'{result:{width}}'"])
def test_diagnostic_with_dynamic_execution_has_no_projection(message):
    after = AFTER.replace("f'Expected {expected}, got {result} for {a} and {b}'", message)
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
