"""Builtin all over string literals no longer consumes a stored generator."""
import pytest

from test_issue_expectation_families import run

PROD = 'def square(value):\n    return value * 2\n'
BEFORE = '''from app.prod import square
def test_square():
    checks = (square(i) == i * i for i in range(2, 5))
    assert all(checks)
'''


def literal_after(argument='"x"'):
    return BEFORE.replace('all(checks)', f'all({argument})')


def marked(ir, side='after'):
    return [assertion for file in ir.files for unit in file.units if getattr(unit, side) is not None
            for assertion in getattr(unit, side).assertions
            if assertion.form == 'tautology' and 'all(' in assertion.text]


@pytest.mark.parametrize('literal', ['"x"', '""', '"\\0"', '"False"', '"台北"'])
@pytest.mark.parametrize('iterator', ['range(2, 5)', 'range(False, 5)', 'range(5)', 'range(4, 1, -1)'])
def test_string_all_is_vacuously_or_elementwise_true_with_original_span(literal, iterator):
    after = literal_after(literal).replace('range(2, 5)', iterator)
    ir, findings, verdict = run(BEFORE, after, PROD)
    found = marked(ir)
    assert len(found) == 1 and found[0].trivial and found[0].strength == 10
    assert after[slice(*found[0].span)].strip() == found[0].text
    assert verdict == 'block' and any(f.rule == 'ASSERT_WEAKENED' and f.severity == 'high' for f in findings)


def test_literal_all_spellings_preserve_the_same_true_predicate():
    ir, findings, verdict = run(literal_after('""'), literal_after('"x"'), PROD)
    assert marked(ir, 'before') and marked(ir)
    assert verdict == 'pass' and not findings


def test_restoring_generator_consumption_is_a_strengthening():
    ir, findings, verdict = run(literal_after(), BEFORE, PROD)
    assert marked(ir, 'before') and not marked(ir)
    assert verdict == 'pass' and not findings


def test_honest_inline_generator_retains_existing_oracle():
    after = BEFORE.replace('    checks = (square(i) == i * i for i in range(2, 5))\n    assert all(checks)',
                           '    assert all(square(i) == i * i for i in range(2, 5))')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert not marked(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('argument', ['[False]', '[""]', 'b"\\0"', '[]', '(True,)',
                                       'unknown', 'str(checks)', '*checks', 'value="x"'])
def test_unknown_or_false_literal_iterables_do_not_get_string_tautology_proof(argument):
    ir, _, _ = run(BEFORE, literal_after(argument), PROD)
    assert not marked(ir)


@pytest.mark.parametrize('old,new', [
    ('from app.prod import square', 'from app.prod import square\nall = lambda x: False'),
    ('from app.prod import square', 'from app.prod import square\nfrom other import unused'),
    ('def test_square():', 'def test_square(all):'),
    ('def test_square():', '@decorate\ndef test_square():'),
    ('    checks =', '    all = lambda x: False\n    checks ='),
    ('    checks =', '    mutate()\n    checks ='),
    ('checks =', 'all ='),
    ('square(i)', 'square(value=i, value=i)'),
    ('square(i)', 'callback(square(i))'),
    ('for i in range(2, 5)', 'for square in range(2, 5)'),
    ('for i in range(2, 5)', 'for __debug__ in range(2, 5)'),
    ('for i in range(2, 5)', 'for i in range(2, 5) if callback(i)'),
    ('i * i', 'expected(i)'),
    ('range(2, 5)', 'range(2, 5, 0)'),
    ('range(2, 5)', 'range(0)'),
    ('range(2, 5)', 'range(10000)'),
    ('range(2, 5)', 'other_range(2, 5)'),
    ('assert all("x")', 'assert all("x"), callback()'),
    ('assert all("x")', 'assert all("x")\n    mutate()'),
])
def test_complete_generator_body_and_builtin_authority_are_required(old,new):
    ir, _, _ = run(BEFORE, literal_after().replace(old,new), PROD)
    assert not marked(ir)


@pytest.mark.parametrize('production', [
    'def square(value):\n    return callback(value)\n',
    'import builtins\ndef square(value):\n    builtins.all = lambda x: False\n    return value\n',
    'def square(value):\n    from tests.test_case import test_square\n    return value\n',
    'class Custom:\n    pass\ndef square(value):\n    return Custom()\n',
])
def test_unknown_or_mutating_production_cannot_prove_builtin_all(production):
    ir, _, _ = run(BEFORE, literal_after(), production)
    assert not marked(ir)


@pytest.mark.parametrize('context', [
    {'src/sitecustomize.py': b'import builtins\nbuiltins.all = lambda x: False\n'},
    {'tests/conftest.py': b'import builtins\nbuiltins.all = lambda x: False\n'},
    {'tests/test_other.py': b'def test_mutate():\n    import builtins\n    builtins.all = lambda x: False\n'},
    {'tests/pytest/__init__.py': b''}, {'app/__init__.py': b''},
    {'pytest.ini': b'[pytest]\ntestpaths=tests/other\n',
     'tests/other/test_padding.py': b'def test_ok():\n    assert True\n'},
])
def test_active_collection_and_startup_authority_are_required(context):
    ir, _, _ = run(BEFORE, literal_after(), PROD, context=context)
    assert not marked(ir)


@pytest.mark.parametrize('dead_expression', ['(all := False)', '(range := False)',
    '(square := False)', '(checks := False)', '(other := False)', '(yield 5)',
    '(yield from [5])', '(await unknown())', '(lambda all: all)', '[all for all in [1]]'])
def test_dead_expected_expression_cannot_hide_lexical_bindings_or_generator_kind(dead_expression):
    expression = f'(i * i if i > 0 else {dead_expression})'
    before = BEFORE.replace('i * i', expression)
    after = literal_after().replace('i * i', expression)
    ir, _, _ = run(before, after, PROD)
    assert not marked(ir)


def test_inert_conditional_expected_arithmetic_without_binders_remains_supported():
    expression = '(i * i if i > 0 else 0)'
    ir, findings, verdict = run(BEFORE.replace('i * i', expression),
                                literal_after().replace('i * i', expression), PROD)
    assert marked(ir) and verdict == 'block'
    assert any(f.rule == 'ASSERT_WEAKENED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('dead_expression', ['f(x=1, x=2)', 'callback()', 'unknown',
    'unknown.attribute', '[i][0]', 'f"{i}"'])
def test_unselected_expected_syntax_must_still_have_closed_numeric_grammar(dead_expression):
    expression = f'(i * i if i > 0 else {dead_expression})'
    ir, _, _ = run(BEFORE.replace('i * i', expression), literal_after().replace('i * i', expression), PROD)
    assert not marked(ir)
