"""A fresh running-sum result cannot mutate literal subject inputs."""
import re

import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_issue_expectation_families import run
from test_sequential_captured_oracles import projected


PROD = '''def subject(values):
    out = []
    total = 0
    for item in values:
        total += item
        out.append(total)
    return out
'''
BEFORE = '''from app.prod import subject
def test_empty():
    assert subject([]) == []
def test_many():
    assert subject([1, 2, 3]) == [1, 3, 6]
def test_single():
    assert subject([5]) == [5]
'''
AFTER = BEFORE.replace('def test_many():\n', '').replace('    assert subject([1, 2, 3]) == [1, 3, 6]',
    '    expected = [1, 3, 6]\n    assert subject([1, 2, 3]) == expected')


@pytest.mark.parametrize('production', [PROD, re.sub(r'\bout\b', 'result', re.sub(r'\btotal\b', 'accumulator', PROD))])
def test_complete_fresh_sum_preserves_merged_literal_expected_oracles(production):
    ir, findings, verdict = run(BEFORE, AFTER, production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('production', [
    PROD.replace('out = []', 'out = values'),
    PROD.replace('total = 0', 'total = values'),
    PROD.replace('out.append(total)', 'values.append(total)'),
    PROD.replace('total += item', 'values += item'),
    PROD.replace('total += item', 'total += callback(item)'),
    PROD.replace('return out', 'return callback(out)'),
    PROD.replace('out = []', 'global out\n    out = []'),
    PROD.replace('out = []', 'out = factory()'),
    PROD.replace('for item in values:', 'for item in callback(values):'),
    PROD.replace('out.append(total)', 'out.append(total)\n        mutate(values)'),
    PROD.replace('total += item', 'total = item\n        total += item'),
    PROD.replace('    return out', '    else:\n        mutate(values)\n    return out'),
    PROD.replace('for item in values:', 'for values in values:'),
    PROD.replace('for item in values:', 'for total in values:'),
])
def test_aliases_external_calls_input_mutation_and_extra_statements_are_not_pure(production):
    assert not _pure_module(production.encode(), 'subject')


def test_fresh_sum_does_not_credit_unknown_input_objects():
    ir, _, _ = run(BEFORE.replace('subject([1, 2, 3])', 'subject(custom)'),
                   AFTER.replace('subject([1, 2, 3])', 'subject(custom)'), PROD)
    assert not projected(ir)


def test_changed_cumulative_answer_is_still_high():
    after = AFTER.replace('expected = [1, 3, 6]', 'expected = [1, 2, 3]')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert verdict == 'block' and any(f.severity == 'high' for f in findings)
