"""Literal string replacement is an expectation value, not an opaque call."""
import ast

import pytest

from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.literal_string_methods import literal_string_replace
from test_issue_expectation_families import run


PROD = 'def squeeze(text):\n    return text.replace(" ", "")\n'
BEFORE = '''from app.prod import squeeze
def test_spaces():
    got = squeeze('a   b')
    assert '  ' not in got
    assert ' ' in got
    assert got == 'a b'
'''
AFTER = '''from app.prod import squeeze
def test_spaces():
    got = squeeze('a   b')
    assert '  ' not in got
    assert got == 'a b'.replace(' ', '')
'''


@pytest.mark.parametrize('flipped', [False, True])
def test_literal_replace_cannot_hide_the_changed_answer(flipped):
    after = AFTER.replace("got == 'a b'.replace(' ', '')", "'a b'.replace(' ', '') == got") if flipped else AFTER
    _, findings, verdict = run(BEFORE, after, PROD)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('expression,expected', [
    ("'a b'.replace(' ', '')", 'ab'), ("'aa'.replace('a', 'b', 1)", 'ba'),
    ("'aa'.replace('a', 'b', 0)", 'aa'), ("'aa'.replace('a', 'b', -1)", 'bb'),
    ("''.replace('', 'x')", 'x'), ("'ab'.replace('', '-')", '-a-b-'),
    ("'大阪'.replace('阪', '版')", '大版'), ("'ab'.replace('z', 'long')", 'ab'),
])
def test_exact_literal_values_and_spans(expression, expected):
    source = f'def test_x():\n    assert value == {expression}\n'
    assertion = parse_python(source.encode(), True).units[0].side.assertions[0]
    assert ast.literal_eval(assertion.right_value) == expected
    assert assertion.right_literal == expression
    assert assertion.text == source[slice(*assertion.span)]


def test_equivalent_literal_spelling_does_not_report_answer_change():
    _, findings, verdict = run(BEFORE, BEFORE.replace("got == 'a b'", "got == 'a b'.replace('x', 'y')"), PROD)
    assert verdict == 'pass'
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('expression', [
    "value.replace(' ', '')", "custom().replace(' ', '')", "'a b'.replace(value, '')",
    "'a b'.replace(' ', callback())", "'a b'.replace(' ', '', count=1)", "'ab'.replace(*args)",
    "'ab'.replace('a', 'b', True)", "'ab'.replace('a', 'b', 1.0)", "'ab'.replace('a', 'b', 4097)",
    "'ab'.replace('a', 'b', -4097)", "'ab'.replace('a', 'b', value)", "'ab'.replace('a')",
    "'ab'.replace('a', 'b', 1, 2)", "b'ab'.replace(b'a', b'b')", "'ab'.upper()",
    "'ab'.replace('a', 'b').replace('b', 'c')", "'ab'.replace('a', 1)",
])
def test_unknown_or_unbounded_expression_does_not_become_a_literal(expression):
    assert literal_string_replace(ast.parse(expression, mode='eval').body) is None


def test_output_size_is_bounded_before_allocating_replacement():
    expression = ast.Call(func=ast.Attribute(value=ast.Constant('a' * 4096), attr='replace', ctx=ast.Load()),
                          args=[ast.Constant(''), ast.Constant('b' * 4096)], keywords=[])
    assert literal_string_replace(expression) is None


def test_chained_range_keeps_existing_unresolved_bound_behavior(monkeypatch):
    from checkwash.frontends.python import frontend
    source = "def test_range():\n    assert 'a' < value() < 'z'.replace('x', 'y')\n"
    current = parse_python(source.encode(), True)
    monkeypatch.setattr(frontend, 'literal_string_replace', lambda node: None)
    assert current == parse_python(source.encode(), True)
