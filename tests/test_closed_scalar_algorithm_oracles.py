"""Whole algorithm grammar proves purity without general loop execution."""
import re

import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_unittest_comparison_truth import run, projected


GCD = '''def subject(a, b):
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a
'''
ORDINAL = '''def subject(n):
    if 10 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
'''


@pytest.mark.parametrize('production,first,second', [
    (GCD, 'subject(-6, -9) == 3', 'subject(8, 9) == 1'),
    (re.sub(r'\bb\b', 'right', re.sub(r'\ba\b', 'left', GCD)),
     'subject(-6, -9) == 3', 'subject(8, 9) == 1'),
    (ORDINAL, 'subject(1) == "1st"', 'subject(11) == "11th"'),
    (ORDINAL.replace('suffix', 'ending'), 'subject(2) == "2nd"', 'subject(21) == "21st"'),
])
def test_complete_closed_algorithms_keep_all_regrouped_oracles(production, first, second):
    before = 'from app.prod import subject\ndef test_first():\n    assert ' + first + '\ndef test_second():\n    assert ' + second + '\n'
    after = 'from app.prod import subject\nimport unittest\nclass TestValues(unittest.TestCase):\n    def test_values(self):\n        self.assertEqual(' + second.replace(' == ', ', ') + ')\n        self.assertEqual(' + first.replace(' == ', ', ') + ')\n'
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('production', [
    GCD.replace('a % b', 'callback(a, b)'),
    GCD.replace('while b:', 'while callback(b):'),
    GCD.replace('    return a', '    mutate(a)\n    return a'),
    GCD.replace('a, b = abs(a), abs(b)', 'a, b = a, b'),
    GCD + '\ndef abs(value):\n    return callback(value)\n',
    'from external import abs\n' + GCD,
    ORDINAL.replace('.get(n % 10, "th")', '.pop(n % 10, "th")'),
    ORDINAL.replace('f"{n}{suffix}"', 'f"{callback(n)}{suffix}"'),
    ORDINAL.replace('f"{n}{suffix}"', 'f"{n:{suffix}}"'),
    ORDINAL.replace('suffix = "th"', 'global suffix\n        suffix = "th"'),
    ORDINAL.replace('{1: "st", 2: "nd", 3: "rd"}', 'source'),
    ORDINAL.replace('suffix = "th"', 'suffix = callback()'),
    ORDINAL.replace('    return f', '    mutate(n)\n    return f'),
])
def test_callbacks_external_state_and_nearby_mutating_grammars_are_not_pure(production):
    assert not _pure_module(production.encode(), 'subject')


@pytest.mark.parametrize('production,call,answer', [(GCD, 'subject(8, 9)', '1'), (ORDINAL, 'subject(1)', '"1st"')])
def test_algorithm_purity_does_not_hide_a_rewritten_answer(production, call, answer):
    before = 'from app.prod import subject\ndef test_answer():\n    assert ' + call + ' == ' + answer + '\n'
    after = before.replace('test_answer', 'test_result').replace(' == ' + answer, ' == 0')
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production,call', [(GCD, 'subject(custom, 9)'), (ORDINAL, 'subject(custom)')])
def test_closed_algorithm_source_never_grants_literal_credit_to_unknown_inputs(production, call):
    before = 'from app.prod import subject\ndef test_first():\n    assert ' + call + ' == 1\n'
    after = before.replace('test_first', 'test_combined')
    ir, _, _ = run(before, after, production)
    assert not projected(ir)
