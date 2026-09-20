"""A local math.gcd wrapper is not the production subject (escape081)."""
import pytest

from test_issue132_subject_replacements import PREFIX, judge


BEFORE = PREFIX + 'def test_total():\n    assert total(12, 8) == 4\n'
AFTER = PREFIX + '''import math
def local_gcd(a, b):
    return math.gcd(a, b)
def test_total():
    assert local_gcd(12, 8) == 4
'''


@pytest.mark.parametrize('source', [
    AFTER,
    AFTER.replace('import math', 'import math as arithmetic').replace('math.gcd', 'arithmetic.gcd'),
    AFTER.replace('import math', 'from math import gcd as euclid').replace('math.gcd', 'euclid'),
])
def test_exact_integer_stdlib_clone_records_subject_replacement(source):
    hits = [finding for finding in judge(BEFORE, source) if finding.rule == 'TEST_PATCHES_SUBJECT']
    assert len(hits) == 1 and hits[0].severity == 'high'


@pytest.mark.parametrize('shadow', [
    'math.py', 'math/__init__.py', 'src/math.py', 'src/math/__init__.py',
    'tests/math.py', 'tests/math/__init__.py',
])
def test_repository_math_shadow_cannot_borrow_stdlib_identity(shadow):
    assert not [finding for finding in judge(BEFORE, AFTER, {shadow: b'from app.billing import total as gcd\n'})
                if finding.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('source', [
    AFTER.replace('return math.gcd(a, b)', 'return total(a, b)'),
    AFTER.replace('import math', 'import custom as math'),
    AFTER.replace('import math', 'from app import math'),
    AFTER.replace('def local_gcd(a, b):', 'def local_gcd(math, b):').replace('math.gcd(a, b)', 'math.gcd(math, b)'),
    AFTER.replace('return math.gcd(a, b)', 'return math.gcd(a, callback(b))'),
    AFTER.replace('def local_gcd(a, b):', '@decorate\ndef local_gcd(a, b):'),
    AFTER.replace('def local_gcd(a, b):', 'def local_gcd(a, b=8):'),
    AFTER.replace('def test_total():', 'def test_total(local_gcd):'),
    AFTER + '\nmath.gcd = total\n',
    AFTER + '\ndef test_mutator():\n    mutate()\n',
])
def test_unknown_helpers_and_binding_mutations_are_not_stdlib_proof(source):
    assert not [finding for finding in judge(BEFORE, source) if finding.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('argument', ['value', 'Indexable()', 'True', '12.0', '"12"'])
def test_custom_index_and_noninteger_inputs_do_not_prove_callback_free_gcd(argument):
    before, after = [source.replace('(12, 8)', f'({argument}, 8)') for source in (BEFORE, AFTER)]
    assert not [finding for finding in judge(before, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


def test_unknown_index_can_reach_production_even_through_math_gcd():
    import math
    seen = []
    class Indexable:
        def __index__(self):
            seen.append('production')
            return 12
    assert math.gcd(Indexable(), 8) == 4
    assert seen == ['production']


def test_input_or_expected_only_changes_and_unused_wrapper_are_not_installations():
    for source in (AFTER.replace('(12, 8)', '(16, 8)'), AFTER.replace('== 4', '== 8'),
                   AFTER.replace('assert local_gcd(', 'assert total(')):
        assert not [finding for finding in judge(BEFORE, source) if finding.rule == 'TEST_PATCHES_SUBJECT']
