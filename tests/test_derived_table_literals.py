"""Closed primitive expectation reduction preserves concrete oracle answers."""

import ast

import pytest

from checkwash.frontends.python.derived_literals import fold_derived
from test_issue_expectation_families import run


CASES = [
    ("bit_count", "n", "5", "2", "bin(n).count('1')", "return bin(n).count('1')"),
    ("digits_only", "s", "'a1b2'", "'12'", "''.join(ch for ch in s if ch.isdigit())",
     "return ''.join(ch for ch in s if ch.isdigit())"),
    ("expand_range", "a,b", "1,3", "[1,2,3]", "list(range(a,b+1))", "return list(range(a,b+1))"),
]


def sources(name, params, values, expected, expression, body, *, alias=False):
    before = f"from app.prod import {name}\ndef test_original():\n    assert {name}({values}) == {expected}\n"
    after = (f"import pytest\nfrom app.prod import {name}\n"
             f"@pytest.mark.parametrize('{params}', [({values})])\n"
             f"def test_values({params}):\n")
    if alias:
        after += f"    expected = {expression}\n"
        expression = "expected"
    after += f"    assert {name}({params}) == {expression}\n"
    return before, after, f"def {name}({params}):\n    {body}\n"


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("alias", [False, True])
def test_equivalent_primitive_expression_keeps_literal_answer(case, alias):
    before, after, production = sources(*case, alias=alias)
    ir, findings, verdict = run(before, after, production)
    assert any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]


@pytest.mark.parametrize("case,changed", [
    (CASES[0], "bin(n).count('11')"),
    (CASES[1], "'-'.join(ch for ch in s if ch.isdigit())"),
    (CASES[2], "list(range(a,b))"),
])
def test_changed_primitive_expression_answer_still_blocks(case, changed):
    before, after, production = sources(*case, alias=True)
    _, findings, verdict = run(before, after.replace(case[4], changed), production)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


@pytest.mark.parametrize("case", CASES)
def test_production_import_or_mutation_withholds_equivalence(case):
    before, after, production = sources(*case)
    ir, _, _ = run(before, after, "import runtime_hooks\n" + production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("shadow", ["bin = replacement\n", "from another import bin\n"])
def test_shadowed_builtin_withholds_equivalence(shadow):
    before, after, production = sources(*CASES[0])
    ir, _, _ = run(before, shadow + after, production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("expression", [
    "list(range(1000000))", "list(range(1, 3, 0))", "bin(2**10000).count('1')",
    "''.join(ch for ch in load() if ch.isdigit())", "''.join(ch for ch in '123' if callback(ch))",
    "''.join(custom(ch) for ch in '123' if ch.isdigit())", "bin(value).count('1')",
])
def test_dynamic_or_oversized_expression_has_no_fold(expression):
    assert fold_derived(ast.parse(expression, mode="eval").body) is None


def test_scalar_fixture_params_need_no_unpack_assignment():
    before, _, production = sources(*CASES[0])
    after = ("import pytest\nfrom app.prod import bit_count\n"
             "@pytest.fixture(params=[5, 0, -7])\ndef n(request):\n    return request.param\n"
             "def test_values(n):\n    assert bit_count(n) == bin(n).count('1')\n")
    assert run(before, after, production)[2] == "pass"


def test_signed_range_bound_remains_a_primitive_scalar():
    case = ("expand_range", "a,b", "-2,2", "[-2,-1,0,1,2]", "list(range(a,b+1))", "return list(range(a,b+1))")
    before, after, production = sources(*case, alias=True)
    assert run(before, after, production)[2] == "pass"


def test_derived_expression_does_not_duplicate_mutable_subject_argument():
    before = "from app.prod import f\ndef test_original():\n    assert f([1], [1]) == [0]\n"
    after = ("import pytest\nfrom app.prod import f\n"
             "@pytest.mark.parametrize('x', [[1]])\ndef test_values(x):\n"
             "    assert f(x, x) == list(range(1))\n")
    ir, _, _ = run(before, after, "def f(a,b):\n    return list(range(1))\n")
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
