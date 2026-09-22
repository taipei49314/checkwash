"""A called assertion helper must still exercise the imported subject."""
import ast

import pytest

from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.subject_replacements import _assertion_scope
from test_issue132_subject_replacements import judge, PREFIX

BEFORE = PREFIX + 'def oracle():\n    assert total([1, 2]) == 3\ndef test_total():\n    oracle()\n'


@pytest.mark.parametrize('setup,callee', [
    ('', 'sum'),
    ('def standin(values):\n    return sum(values)\n', 'standin'),
    ('from unittest.mock import Mock\nstandin = Mock(return_value=3)\n', 'standin'),
])
def test_closed_helper_subject_replacement_is_detected(setup, callee):
    after = BEFORE.replace('def oracle():', setup + 'def oracle():').replace('assert total(', f'assert {callee}(')
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' and f.severity == 'high' for f in judge(BEFORE, after))


def test_identity_boolean_helper_replacement_masks_real_failure():
    before = PREFIX + 'def oracle():\n    assert total([1, 2]) is True\ndef test_total():\n    oracle()\n'
    after = before.replace('def oracle():', 'def standin(values):\n    return bool(values)\ndef oracle():').replace(
        'assert total(', 'assert standin(')
    old = {'total': lambda values: False}
    new = {'total': lambda values: False}
    exec(before.removeprefix(PREFIX), old)
    exec(after.removeprefix(PREFIX), new)
    with pytest.raises(AssertionError):
        old['test_total']()
    new['test_total']()
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' for f in judge(before, after))


def test_forwarding_helper_and_same_subject_result_remain_silent():
    after = BEFORE.replace('def oracle():', 'def forward(values):\n    return total(values)\ndef oracle():').replace(
        'assert total(', 'assert forward(')
    assert not [f for f in judge(BEFORE, after) if f.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('source', [
    BEFORE.replace('def oracle():', 'def oracle(total=sum):'),
    BEFORE.replace('def oracle():', '@decorator\ndef oracle():'),
    BEFORE + 'oracle = other\n',
    BEFORE.replace('    oracle()', '    mutate()\n    oracle()'),
    BEFORE.replace('    oracle()', '    if enabled:\n        oracle()'),
    BEFORE.replace('def test_total():', 'def test_total(oracle):'),
    BEFORE.replace('def test_total():', 'from provider import *\ndef test_total():'),
    BEFORE.replace('def test_total():', 'def test_total():\n    oracle = other'),
])
def test_unknown_helper_dispatch_does_not_borrow_module_scope(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    inherited = [a for unit in parsed.units for a in unit.side.assertions if a.inherited]
    for assertion in inherited:
        assert _assertion_scope(ast.parse(source), 'test_total', assertion) is None
