"""An added exception oracle cannot hide a removed old exception or answer."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = ("def factorial(n):\n    if n < 0:\n        raise ValueError('n must be >= 0')\n"
              "    result = 1\n    for i in range(1,n+1):\n        result *= i\n    return result\n")
BEFORE = ("from app.prod import factorial\ndef assert_fact(n,expected):\n    assert factorial(n) == expected\n"
          "def test_zero():\n    assert_fact(0,1)\ndef test_one():\n    assert_fact(1,1)\n"
          "def test_five():\n    assert_fact(5,120)\n")
AFTER = ("import pytest\nfrom app.prod import factorial\n"
         "@pytest.fixture(params=[(0,1),(1,1),(5,120)])\ndef test_data(request):\n    return request.param\n"
         "def test_factorial(test_data):\n    n,expected = test_data\n"
         "    with pytest.raises(ValueError) as exc_info:\n        factorial(-1)\n"
         "    assert str(exc_info.value) == 'n must be >= 0'\n    assert factorial(n) == expected\n")


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_added_raises_and_exact_message_are_retained_with_fixture_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    unit = next(unit for unit in ir.files[0].units if unit.qualname.startswith('test_exception_'))
    assert unit.before is None
    assert len(unit.after.assertions) == 2
    snippets = [AFTER.encode()[slice(*assertion.span)].decode() for assertion in unit.after.assertions]
    assert snippets[0].startswith('with pytest.raises(ValueError)')
    assert snippets[1].startswith('assert str(exc_info.value)')


def test_changed_original_answer_is_still_blocked_beside_added_raises():
    _, findings, verdict = run(BEFORE, AFTER.replace('(5,120)', '(5,119)'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('pytest.raises(ValueError)', 'pytest.raises(Exception)'),
    ('factorial(-1)', 'factorial(-2)'),
    ("'n must be >= 0'", "'different'"),
    (" as exc_info", ""),
    ('    assert str(exc_info.value) == \'n must be >= 0\'\n', ''),
])
def test_existing_exception_changes_never_acquire_projection(change):
    before = 'import pytest\n' + BEFORE + ("def test_negative():\n"
             "    with pytest.raises(ValueError) as exc_info:\n        factorial(-1)\n"
             "    assert str(exc_info.value) == 'n must be >= 0'\n")
    ir, _, _ = run(before, AFTER.replace(*change), PRODUCTION)
    assert not projected(ir)


def test_removing_an_exception_only_test_never_acquires_projection():
    before = 'import pytest\n' + BEFORE + 'def test_negative():\n    with pytest.raises(ValueError):\n        factorial(-1)\n'
    after = AFTER[:AFTER.index('    with pytest.raises')] + '    assert factorial(n) == expected\n'
    assert not projected(run(before, after, PRODUCTION)[0])


@pytest.mark.parametrize('change', [
    ('import pytest\n', 'import pytest\nValueError = custom\n'),
    ('import pytest\n', 'import pytest\nstr = custom\n'),
    ('import pytest\n', 'import pytest\nimport mutator\n'),
    ('factorial(-1)', 'factorial(n)'),
    ('factorial(-1)', 'callback()'),
    ('pytest.raises(ValueError)', 'pytest.raises(ValueError, check=callback)'),
    ('assert str(exc_info.value)', 'assert format(exc_info.value)'),
    ('    assert factorial(n) == expected', '    inspect(exc_info)\n    assert factorial(n) == expected'),
])
def test_unknown_authority_dispatch_or_exception_use_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'import mutator\n' + PRODUCTION,
    PRODUCTION.replace('    result = 1', '    mutate()\n    result = 1'),
    PRODUCTION.replace('ValueError', 'CustomError'),
])
def test_effectful_or_custom_exception_production_has_no_projection(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_same_exact_exception_survives_carrier_change():
    before = 'import pytest\n' + BEFORE + ("def test_negative():\n"
             "    with pytest.raises(ValueError) as exc_info:\n        factorial(-1)\n"
             "    assert str(exc_info.value) == 'n must be >= 0'\n")
    ir, findings, verdict = run(before, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    unit = next(unit for unit in ir.files[0].units if unit.qualname.startswith('test_exception_'))
    assert len(unit.before.assertions) == len(unit.after.assertions) == 2
