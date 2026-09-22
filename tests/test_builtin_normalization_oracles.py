"""Constant builtin normalizations preserve text while losing value evidence."""
import dataclasses

import pytest

from checkwash.ir import strength as S
from test_issue_expectation_families import run

PROD = 'def identity(value):\n    return value + 1\n'
BEFORE = '''from app.prod import identity
def test_value():
    assert identity(3) == 3
'''


def after(form='string'):
    expression = ('str(identity(3))[:0] == str(3)[:0]' if form == 'string' else
                  '(len(repr(identity(3))) > 0) == (len(repr(3)) > 0)')
    return BEFORE.replace('identity(3) == 3', expression)


def marked(ir, side='after', form='tautology'):
    return [a for file in ir.files for unit in file.units if getattr(unit, side) is not None
            for a in getattr(unit, side).assertions if a.form == form]


@pytest.mark.parametrize('form', ['string', 'repr'])
@pytest.mark.parametrize('edit', [lambda text: text, lambda text: '"中文"\n' + text,
                                  lambda text: text.replace('\n', '\r\n'),
                                  lambda text: text.replace('import identity', 'import identity as subject')
                                  .replace('identity(3)', 'subject(3)')])
def test_normalization_loses_value_check_but_retains_actual_assertion(form, edit):
    old, new = edit(BEFORE), edit(after(form))
    ir, findings, verdict = run(old, new, PROD)
    found = marked(ir)
    assert len(found) == 1 and found[0].strength == S.TAUTOLOGY and found[0].trivial
    assert new.replace('\r\n', '\n')[slice(*found[0].span)].strip() == found[0].text
    assert verdict == 'block' and any(f.rule == 'ASSERT_WEAKENED' and f.severity == 'high' for f in findings)


def test_compound_normalization_and_type_only_helper_both_retain_classification():
    before = BEFORE.replace('    assert identity(3) == 3', '    assert identity(3) == 3\n    assert identity(4) == 4')
    new = after() + '    check(identity(4), 4)\ndef check(actual, expected):\n    assert type(actual) == type(expected)\n'
    ir, findings, verdict = run(before, new, PROD)
    assert len(marked(ir)) == len(marked(ir, form='type_shape')) == 1
    assert verdict == 'block' and any(f.rule == 'ASSERT_WEAKENED' for f in findings)


@pytest.mark.parametrize('production', [PROD, 'def identity(value):\n    return value\n'])
def test_honest_exact_helper_keeps_the_original_subject_and_answer(production):
    new = BEFORE.replace('assert identity(3) == 3', 'check(identity(3), 3)')
    new += '\ndef check(actual, expected):\n    assert actual == expected\n'
    ir, findings, verdict = run(BEFORE, new, production)
    assert not marked(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('form', ['string', 'repr'])
def test_same_normalization_is_stable_and_restoring_exact_value_has_no_weakening_marker(form):
    ir, findings, verdict = run(after(form), after(form), PROD)
    assert marked(ir, 'before') and marked(ir) and verdict == 'pass' and not findings
    ir, findings, verdict = run(after(form), BEFORE, PROD)
    assert marked(ir, 'before') and not marked(ir)
    assert not any(f.rule == 'ASSERT_WEAKENED' for f in findings)
    # Existing syntactic substitution policy still handles the reverse rewrite.
    assert [(f.rule, f.severity) for f in findings] == [('ASSERT_SUBSTITUTED', 'high')]


@pytest.mark.parametrize('value', ['None', 'False', '0', '1.5', '""', '"台北"', 'b""',
                                  '()', '[]', '{}', '{1, 2}', '[[], {}]'])
@pytest.mark.parametrize('form', ['string', 'repr'])
def test_primitive_results_cannot_override_str_or_repr(value, form):
    assert marked(run(BEFORE, after(form), 'def identity(value):\n    return ' + value + '\n')[0])


@pytest.mark.parametrize('expression', [
    'str(identity(3))[:1] == str(3)[:1]', 'str(identity(3))[1:0] == str(3)[1:0]',
    'str(identity(3))[:False] == str(3)[:False]', 'str(identity(3))[::0] == str(3)[::0]',
    'str(identity(3))[:0:1] == str(3)[:0:1]',
    'str(identity(3))[:0] != str(3)[:0]', 'str(identity(3))[:0] is str(3)[:0]',
    'str(identity(3))[:0] == str(3)[:0] == ""', 'str(identity(3))[:0] == ""',
    '(len(repr(identity(3))) >= 0) == (len(repr(3)) >= 0)',
    '(len(repr(identity(3))) > 1) == (len(repr(3)) > 1)',
    '(len(str(identity(3))) > 0) == (len(str(3)) > 0)',
    '(len(repr(identity(3))) > 0) == True',
    'str(identity(value=3, value=3))[:0] == str(3)[:0]',
    'str(callback(identity(3)))[:0] == str(3)[:0]',
    'str(identity(3))[:0] == str(callback())[:0]',
    'str(identity(3), encoding="utf8")[:0] == str(3)[:0]',
])
def test_unknown_or_nonconstant_operations_do_not_get_the_new_marker(expression):
    ir, _, _ = run(BEFORE, BEFORE.replace('identity(3) == 3', expression), PROD)
    assert not marked(ir)


@pytest.mark.parametrize('name', ['str', 'repr', 'len'])
@pytest.mark.parametrize('binding', [
    'def NAME(actual, expected):\n    assert actual == expected\n',
    'from elsewhere import value as NAME\n', 'NAME = callback\n',
    'class NAME:\n    pass\n',
])
def test_global_builtin_bindings_withhold_proof(name, binding):
    assert not marked(run(BEFORE, binding.replace('NAME', name) + after(), PROD)[0])


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('def test_value():', 'def test_value(str):'),
    lambda s: s.replace('def test_value():', 'def test_value() -> callback():'),
    lambda s: s.replace('def test_value():', '@decorate\ndef test_value():'),
    lambda s: s.replace('    assert', '    repr = callback\n    assert'),
    lambda s: s.replace('    assert', '    del len\n    assert'),
    lambda s: s.replace('    assert', '    mutate()\n    assert'),
    lambda s: s.replace('identity(3)', 'identity((len := 3))'),
    lambda s: s.replace('identity(3)', 'identity((3 if True else (str := 4)))'),
    lambda s: s.replace('identity(3)', 'identity((3 if True else f(x=1, x=2)))'),
    lambda s: s + 'def setUpModule():\n    mutate()\n',
])
def test_local_binders_invalid_source_and_execution_barriers_withhold(edit):
    assert not marked(run(BEFORE, edit(after()), PROD)[0])


@pytest.mark.parametrize('production', [
    'class Custom:\n    def __repr__(self):\n        return ""\ndef identity(value):\n    return Custom()\n',
    'def identity(value):\n    return callback(value)\n',
    'import builtins\ndef identity(value):\n    builtins.str = callback\n    return value\n',
    'def identity(value):\n    from tests.test_case import test_value\n    return value\n',
])
def test_custom_dispatch_and_unknown_production_are_not_primitive_proof(production):
    assert not marked(run(BEFORE, after(), production)[0])


@pytest.mark.parametrize('context', [
    {'src/sitecustomize.py': b'import builtins\nbuiltins.str = custom\n'},
    {'conftest.py': b'import builtins\nbuiltins.repr = custom\n'},
    {'src/app/__init__.py': b'import builtins\nbuiltins.len = custom\n'},
    {'tests/test_sibling.py': b'def test_other():\n    import builtins\n    builtins.str = custom\n'},
    {'pytest.py': b''}, {'tests/pytest/__init__.py': b''}, {'src/builtins.py': b''},
    {'app/__init__.py': b''}, {'pytest.ini': b'[pytest]\ntestpaths=tests/other\n'},
])
def test_full_snapshot_builtin_source_and_collection_authority_is_required(context):
    assert not marked(run(BEFORE, after(), PROD, context=context)[0])


def test_actual_predicate_and_all_other_ir_fields_remain_unchanged(monkeypatch):
    from checkwash.frontends.python import builtin_normalization_oracles
    current = dataclasses.asdict(run(BEFORE, after(), PROD)[0].files[0])
    monkeypatch.setattr(builtin_normalization_oracles, '_module', lambda _: None)
    ordinary = dataclasses.asdict(run(BEFORE, after(), PROD)[0].files[0])
    ordinary['units'][0]['after']['assertions'][0].update(form='tautology', strength=S.TAUTOLOGY, trivial=True)
    ordinary['units'][0]['delta']['assertion_pairs'][0]['strength_change'] = -80
    assert current == ordinary
