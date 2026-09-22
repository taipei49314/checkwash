"""Boolean answer replacement remains visible across Eq/Is carrier changes."""
import ast

import pytest

from checkwash.frontends.python.expected_constants import folded_expected
from test_issue_expectation_families import run


PRODUCTION = 'def between(x,lo,hi):\n    return lo < x < hi\n'
BEFORE = ('from app.prod import between\ndef test_lower():\n    assert between(0,0,10) is True\n'
          'def test_upper():\n    assert between(10,0,10) is True\n'
          'def test_below():\n    assert between(-1,0,10) is False\n')
AFTER = ('from app.prod import between\ndef expected_value(x,lo,hi):\n    return lo < x < hi\n'
         'def test_lower():\n    assert between(0,0,10) == expected_value(0,0,10)\n'
         'def test_upper():\n    assert between(10,0,10) == expected_value(10,0,10)\n'
         'def test_below():\n    assert between(-1,0,10) == expected_value(-1,0,10)\n')


def provenance(ir):
    return [event for file in ir.files for event in file.expected_provenance_events]


@pytest.mark.parametrize('before_op,after_op', [('is','=='), ('==','is'), ('is','is'), ('==','==')])
def test_copied_chain_helper_retains_only_changed_boolean_answers(before_op, after_op):
    ir, findings, verdict = run(BEFORE.replace(' is ', f' {before_op} '),
                               AFTER.replace(' == expected_value', f' {after_op} expected_value'), PRODUCTION)
    assert verdict == 'block'
    assert {f.unit for f in findings if f.rule == 'EXPECTATION_DEFINITION_CHANGED'} == {'test_lower', 'test_upper'}
    assert all(event[-2:] == ('True','False') for event in provenance(ir))
    for unit in ir.files[0].units:
        if unit.before and unit.after:
            assert unit.before.assertions[0].strength == unit.after.assertions[0].strength == 90


def test_honest_boolean_helper_extraction_does_not_acquire_a_finding():
    before = BEFORE.replace('is True', 'is False')
    ir, findings, verdict = run(before, AFTER, PRODUCTION)
    assert not provenance(ir) and not findings and verdict == 'pass'


def test_reversed_helper_comparison_keeps_the_same_subject():
    after = AFTER.replace('between(0,0,10) == expected_value(0,0,10)', 'expected_value(0,0,10) == between(0,0,10)')
    _, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTATION_DEFINITION_CHANGED' and f.unit == 'test_lower' for f in findings)


@pytest.mark.parametrize('source', [
    AFTER.replace('return lo < x < hi', 'return external(x,lo,hi)'),
    AFTER.replace('def expected_value(x,lo,hi):', '@external\ndef expected_value(x,lo,hi):'),
    AFTER.replace('def expected_value(x,lo,hi):', 'def expected_value(x,lo,hi=external()):'),
    AFTER.replace('from app.prod import between', 'from app.prod import between\nimport mutator'),
    AFTER.replace('return lo < x < hi', 'globals()["expected_value"] = replacement\n    return lo < x < hi'),
])
def test_unknown_helper_authority_cannot_create_a_boolean_transition(source):
    ir, _, _ = run(BEFORE, source, PRODUCTION)
    assert not provenance(ir)


def test_different_subject_inputs_do_not_become_an_answer_change():
    after = AFTER.replace('between(0,0,10)', 'between(1,0,10)').replace('between(10,0,10)', 'between(9,0,10)')
    assert not provenance(run(BEFORE, after, PRODUCTION)[0])


def test_multiple_operator_obligations_are_not_arbitrarily_cross_paired():
    before = ('from app.prod import between\ndef test_one():\n'
              '    assert between(0,0,10) is True\n    assert between(0,0,10) is False\n')
    after = ('from app.prod import between\ndef answer():\n    return False\ndef test_one():\n'
             '    assert between(0,0,10) == answer()\n    assert between(0,0,10) == answer()\n')
    assert not provenance(run(before, after, PRODUCTION)[0])


def test_numeric_one_is_not_relabelled_as_a_boolean_expected_value():
    after = AFTER.replace('return lo < x < hi', 'return 1')
    assert not provenance(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('expression,answer', [
    ('0 < 0 < 10', False), ('0 <= 0 < 10', True), ('0 < 3 <= 10', True),
    ('0 < -1 < 10', False), ('1 < 0 < 1 / 0', False), ('"a" < "b" < "c"', True),
])
def test_chain_folding_is_closed_bounded_and_explicitly_opted_in(expression, answer):
    tree = ast.parse(expression, mode='eval').body
    assert folded_expected(tree, lambda _: False) is None
    folded = folded_expected(tree, lambda _: False, boolean_logic=True)
    assert isinstance(folded, ast.Constant) and folded.value is answer


@pytest.mark.parametrize('expression', ['0 < 1 < external()', '0 < object < 10', '0 < 1 < 1 / 0', 'True is 1'])
def test_unknown_or_raising_chain_does_not_fold(expression):
    assert folded_expected(ast.parse(expression, mode='eval').body, lambda _: False, boolean_logic=True) is None
