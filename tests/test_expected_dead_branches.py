"""Dead branches still own Python binding and compilation behavior."""
import ast

import pytest

from checkwash.frontends.python.expected_constants import folded_expected
from test_issue_expectation_families import run
from test_parameter_helper_answers import BEFORE, AFTER, PRODUCTION


@pytest.mark.parametrize('expression', [
    '1 if True else (len := 0)',
    '1 if True else (yield 2)',
    '1 if True else (yield from ())',
    '1 if True else (await result)',
    '1 if True else (lambda x, x: x)',
    '1 if True else unknown(x=1, x=2)',
    '1 if True else len(x=1, x=2)',
    '1 if True else [value for value in source]',
    '1 if True else ((len := n) for n in source)',
    'True or (len := 0)',
    'False and (yield 1)',
])
def test_lexical_and_unsupported_syntax_cannot_hide_in_unselected_branches(expression):
    assert folded_expected(ast.parse(expression, mode='eval').body, lambda name: True, boolean_logic=True) is None


@pytest.mark.parametrize('old,new', [
    ('len(s) <= 3', 'len(s) <= 3 if True else (len := 0)'),
    ('return s\n', 'return s if True else (yield "x")\n'),
    ('return s\n', 'return s if True else (await s)\n'),
    ('return s\n', 'return s if True else (lambda s, s: s)\n'),
])
def test_actual_helper_with_dead_lexical_effect_does_not_gain_table_equivalence(old, new):
    result = run(BEFORE.replace('== "ba"', '== "ab"'), AFTER.replace(old, new), PRODUCTION)
    assert not any(unit.qualname.startswith('test_concrete_') for unit in result[0].files[0].units)


@pytest.mark.parametrize('expression,wanted', [
    ('1 if True else 1/0', 1),
    ('2 if 3 > 1 else len(())', 2),
    ('"abc"[::-1] if 1 < 2 else ""', 'cba'),
    ('len([1, 2])', 2),
    ('math.prod((2, 3))', 6),
    ('2 if 1 < 2 < 3 else 0', 2),
])
def test_closed_branches_keep_lazy_values_without_running_unselected_errors(expression, wanted):
    result = folded_expected(ast.parse(expression, mode='eval').body, lambda name: True, boolean_logic=True)
    assert result is not None and ast.literal_eval(result) == wanted
