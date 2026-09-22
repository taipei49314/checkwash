"""Literal table labels cannot conceal the helper's effective answer."""
import pytest

from checkwash.frontends.python import table_oracles
from test_issue_expectation_families import run

PRODUCTION = 'def reverse_string(s):\n    return s if len(s) <= 3 else s[::-1]\n'
BEFORE = '''from app.prod import reverse_string
def test_short():
    assert reverse_string("ab") == "ba"
'''
AFTER = '''import pytest
from app.prod import reverse_string
def calculate_expected(s):
    if len(s) <= 3:
        return s
    return s[::-1]
@pytest.mark.parametrize("input_string, expected", [("ab", "ba"), ("abcd", "dcba")])
def test_reverse_string(input_string, expected):
    assert reverse_string(input_string) == calculate_expected(input_string)
'''


def projection(source):
    result = table_oracles._module(source.encode(), baseline=False)
    return result is not None and any(form == 'parameter-helper-answer' for _, form in result[6])


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('calculate_expected', 'answer'),
    AFTER.replace('input_string', 'value').replace('expected)', 'wanted)').replace(', expected"', ', wanted"'),
    AFTER.replace('len(s) <= 3', 'len(s) < 4'),
    AFTER.replace('return s\n', 'return s[:]\n'),
])
def test_effective_helper_answer_is_retained_for_the_original_input(after):
    result = run(BEFORE, after, PRODUCTION)
    assert result[2] == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in result[1])
    assert projection(after)


def test_honest_helper_preserves_good_and_wrong_production_checks():
    honest = AFTER.replace('return s\n', 'return s[::-1]\n')
    assert projection(honest)
    for production in [PRODUCTION, 'def reverse_string(s):\n    return s[::-1]\n']:
        assert run(BEFORE, honest, production)[2] == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('calculate_expected(input_string)', 'calculate_expected(expected)'),
    AFTER.replace('calculate_expected(input_string)', 'calculate_expected(callback())'),
    AFTER.replace('calculate_expected(input_string)', 'calculate_expected(s=input_string)'),
    AFTER.replace('reverse_string(input_string)', 'reverse_string(s=input_string)'),
    AFTER.replace('== calculate_expected', 'is calculate_expected'),
    AFTER.replace('def calculate_expected(s):', 'def calculate_expected(s=callback()):'),
    AFTER.replace('def calculate_expected(s):', 'def calculate_expected(s: callback()):'),
    AFTER.replace('def calculate_expected(s):', '@decorator\ndef calculate_expected(s):'),
    AFTER.replace('def calculate_expected(s):', 'def calculate_expected(len):'),
    AFTER.replace('    if len(s)', '    mutate()\n    if len(s)'),
    AFTER.replace('return s\n', 'return subject(s)\n'),
    AFTER.replace('return s\n', 'return s.strip()\n'),
    AFTER.replace('return s\n', 'return global_answer\n'),
    AFTER.replace('return s\n', 'return [s]\n'),
    AFTER.replace('return s\n', 'return None\n'),
    AFTER.replace('return s[::-1]', 'return s[999]'),
    AFTER.replace('    return s[::-1]\n', ''),
    AFTER.replace('def test_reverse_string(input_string, expected):', 'def test_reverse_string(input_string, expected, request):'),
    AFTER.replace('def test_reverse_string(input_string, expected):', 'def test_reverse_string(input_string, expected=callback()):'),
    AFTER.replace('    assert reverse_string', '    mutate()\n    assert reverse_string'),
    AFTER.replace('calculate_expected(input_string)\n', 'calculate_expected(input_string), callback()\n'),
    AFTER.replace('[("ab", "ba"), ("abcd", "dcba")]', 'rows'),
    AFTER.replace('("ab", "ba")', '("ab", callback())'),
    AFTER.replace('("ab", "ba")', '("ab", 1)'),
    AFTER.replace('])', '], indirect=True)'),
    AFTER + '\ncalculate_expected = callback\n',
    AFTER + '\ndef other():\n    return calculate_expected("ab")\n',
    AFTER.replace('from app.prod', 'import mutator\nfrom app.prod'),
])
def test_unknown_helpers_and_consumers_do_not_receive_projection(after):
    assert not projection(after)


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.len = lambda value: 1\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef effect():\n    mutate()\n'},
    {'tests/test_other.py': b'import app.prod\napp.prod.reverse_string = lambda value: value\n'},
    {'app/prod.py': PRODUCTION.encode()},
])
def test_runtime_and_provider_authority_withhold_concrete_helper_projection(context):
    result = run(BEFORE, AFTER, PRODUCTION, context=context)
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in result[1])


@pytest.mark.parametrize('production', [
    'def reverse_string(s):\n    mutate()\n    return s\n',
    'from tests.test_case import calculate_expected\n' + PRODUCTION,
    'import builtins\nbuiltins.len = lambda value: 1\n' + PRODUCTION,
])
def test_both_production_sources_must_be_closed(production):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, AFTER, production)[1])


@pytest.mark.parametrize('old,new', [
    (BEFORE, AFTER.replace('("ab", "ba")', '("ac", "ba")')),
    (BEFORE + BEFORE[BEFORE.index('def test_short'):].replace('test_short', 'test_again'), AFTER),
    (BEFORE, AFTER.replace('[("ab", "ba"), ("abcd", "dcba")]', '[("abcd", "dcba"), ("ab", "ba")]')),
])
def test_input_prefix_and_original_oracle_multiplicity_remain_required(old, new):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(old, new, PRODUCTION)[1])
