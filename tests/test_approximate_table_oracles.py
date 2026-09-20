"""Approximate table answers retain the original numeric oracle and tolerance."""

import pytest

from test_issue_expectation_families import run


BEFORE = "from app.prod import divide\ndef test_original():\n    assert divide(10, 3) == 3\n"
PRODUCTION = "def divide(a, b):\n    return a / b\n"


def table(expected, *, cell=False):
    first = expected if cell else "3.3333333333333335"
    answer = "expected" if cell else expected
    return ("import pytest\nfrom app.prod import divide\n"
            f"@pytest.mark.parametrize('a, b, expected', [(10, 3, {first}), (9, 3, 3.0)])\n"
            f"def test_division(a, b, expected):\n    assert divide(a, b) == {answer}\n")


@pytest.mark.parametrize("cell", [False, True])
@pytest.mark.parametrize("keywords", ["", ", rel=0.001", ", abs=0.1", ", rel=0.001, abs=0.1, nan_ok=False"])
def test_literal_answer_replaced_by_approx_in_renamed_table_blocks(cell, keywords):
    expected = f"pytest.approx({'3.3333333333333335' if cell else 'expected'}{keywords})"
    ir, findings, verdict = run(BEFORE, table(expected, cell=cell), PRODUCTION)
    assert any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block", [(f.rule, f.severity) for f in findings]


def test_existing_equal_approx_expectation_can_move_into_table():
    before = "import pytest\n" + BEFORE.replace("== 3", "== pytest.approx(3.3333333333333335, abs=0.001)")
    after = table("pytest.approx(3.3333333333333335, abs=0.001)", cell=True)
    assert run(before, after, PRODUCTION)[2] == "pass"


def test_existing_approx_tolerance_widening_still_blocks():
    before = "import pytest\n" + BEFORE.replace("== 3", "== pytest.approx(3.3333333333333335, abs=0.001)")
    after = table("pytest.approx(3.3333333333333335, abs=100)", cell=True)
    _, findings, verdict = run(before, after, PRODUCTION)
    assert verdict == "block"
    assert any(f.rule == "TOLERANCE_LOOSENED" for f in findings)


def test_numeric_sequence_approx_keeps_tuple_answer_change_visible():
    before = "from app.prod import min_max\ndef test_original():\n    assert min_max([3, 1, 2]) == (1, 3)\n"
    after = ("import pytest\nfrom app.prod import min_max\n"
             "@pytest.mark.parametrize('xs, expected', [([3, 1, 2], (3, 1)), ([4], (4, 4))])\n"
             "def test_values(xs, expected):\n    assert min_max(xs) == pytest.approx(expected)\n")
    assert run(before, after, "def min_max(xs):\n    return max(xs), min(xs)\n")[2] == "block"


@pytest.mark.parametrize("expected", [
    "pytest.approx(load())", "pytest.approx(3.3, rel=load())", "pytest.approx(3.3, abs=-1)",
    "pytest.approx(3.3, unexpected=1)", "pytest.approx(3.3, **options)",
    "pytest.approx(float('nan'))", "pytest.approx([[3.3]])",
])
def test_unproved_approx_cells_do_not_get_concrete_projection(expected):
    ir, _, _ = run(BEFORE, table(expected, cell=True), PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("context", [
    {"pytest.py": b"def approx(value):\n    return value\n"},
    {"conftest.py": b"def pytest_sessionstart(session):\n    configure()\n"},
])
def test_unknown_approx_authority_has_no_projection(context):
    ir, _, _ = run(BEFORE, table("pytest.approx(3.3)", cell=True), PRODUCTION, context=context)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_production_mutation_of_approx_withholds_projection():
    production = "import pytest\ndef divide(a, b):\n    pytest.approx = lambda expected: 3\n    return a / b\n"
    ir, _, _ = run(BEFORE, table("pytest.approx(3.3)", cell=True), production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_approx_object_cannot_be_substituted_into_subject_input():
    after = table("pytest.approx(3.3)", cell=True).replace("divide(a, b)", "divide(expected, b)")
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
