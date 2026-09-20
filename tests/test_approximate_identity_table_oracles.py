"""Identity-to-approx changes preserve operators while pairing concrete calls."""

import pytest

from test_issue_expectation_families import run


BEFORE = ("from app.prod import safe_div\n"
          "def test_ok():\n    assert safe_div(6, 3) == 2\n"
          "def test_zero():\n    assert safe_div(1, 0) is None\n")
AFTER = ("import pytest\nfrom app.prod import safe_div\n"
         "@pytest.mark.parametrize('a,b,expected', [(6,3,2),(1,0,0)])\n"
         "def test_division(a,b,expected):\n    assert safe_div(a,b) == pytest.approx(expected)\n")
PRODUCTION = "def safe_div(a,b):\n    if b == 0:\n        return 0\n    return a/b\n"


def test_renamed_identity_oracle_to_approximate_table_blocks():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == "block"
    assert {f.rule for f in findings} >= {"ASSERT_WEAKENED", "EXPECTED_VALUE_CHANGED"}
    pairs = [(unit.before.assertions[0], unit.after.assertions[0]) for unit in ir.files[0].units
             if unit.before is not None and unit.after is not None]
    assert any("is None" in before.text and "pytest.approx(0)" in after.text for before, after in pairs)


@pytest.mark.parametrize("singleton,answer", [("None", "0"), ("True", "1"), ("False", "0")])
def test_identity_operator_is_retained_for_ordinary_weakening(singleton, answer):
    before = f"from app.prod import f\ndef test_original():\n    assert f(3) is {singleton}\n"
    after = ("import pytest\nfrom app.prod import f\n"
             f"@pytest.mark.parametrize('n,expected', [(3,{answer})])\n"
             "def test_values(n,expected):\n    assert f(n) == pytest.approx(expected)\n")
    _, findings, verdict = run(before, after, f"def f(n):\n    return {answer}\n")
    assert verdict == "block"
    assert any(f.rule == ("EXPECTED_VALUE_CHANGED" if singleton == "None" else "ASSERT_WEAKENED") for f in findings)


@pytest.mark.parametrize("rows", ["[(1,0,0),(6,3,2)]", "[(6,3,2),(1,1,0)]", "[(6,3,2)]"])
def test_different_or_missing_inputs_do_not_gain_operator_pairing(rows):
    ir, _, _ = run(BEFORE, AFTER.replace("[(6,3,2),(1,0,0)]", rows), PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("replacement", ["expected", "None", "True"])
def test_plain_identity_to_equality_is_not_claimed_equivalent(replacement):
    ir, _, _ = run(BEFORE, AFTER.replace("pytest.approx(expected)", replacement), PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_operator_transition_with_unproved_production_has_no_projection():
    ir, _, _ = run(BEFORE, AFTER, "import hooks\n" + PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
