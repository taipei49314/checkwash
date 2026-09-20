"""An exact ordered table cannot silently exchange production for min/max."""
import ast

import pytest

from test_issue_expectation_families import run

PRODUCTION = 'def biggest(xs):\n    return min(xs)\n'
BEFORE = '''from app.prod import biggest
def test_biggest():
    cases = [([1, 2, 3], 3), ([9, 0, 4], 9)]
    for xs, expected in cases:
        assert biggest(xs) == expected
'''
AFTER = '''from app.prod import biggest
import pytest
@pytest.mark.parametrize("xs, expected", [([1, 2, 3], 1), ([9, 0, 4], 0)])
def test_biggest(xs, expected):
    assert min(xs) == expected
'''


def events(before=BEFORE, after=AFTER, production=PRODUCTION, context=None):
    result = run(before, after, production, context=context)
    return result, result[0].globals.subject_installations


@pytest.mark.parametrize('builtin', ['min', 'max'])
@pytest.mark.parametrize('answers', [False, True])
def test_closed_builtin_replacement_emits_only_existing_installation_evidence(builtin, answers):
    after = AFTER.replace('min(xs)', builtin + '(xs)')
    if answers:
        after = after.replace('([1, 2, 3], 1)', '([1, 2, 3], 3)').replace('([9, 0, 4], 0)', '([9, 0, 4], 9)')
    result, evidence = events(after=after)
    assert result[2] == 'block'
    assert [(f.rule, f.severity) for f in result[1]] == [('TEST_PATCHES_SUBJECT', 'high')]
    assert len(evidence) == 1 and evidence[0][:3] == ('tests/test_case.py', 'test_biggest', 'app.prod.biggest')
    assert after[slice(*evidence[0][4])] == evidence[0][3] == 'assert ' + builtin + '(xs) == expected'
    unit = result[0].files[0].units[0]
    assert unit.before.assertions[0].text == 'assert biggest(xs) == expected'
    assert unit.after.assertions[0].text == 'assert ' + builtin + '(xs) == expected'


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('[1, 2, 3]', '(-1, 2.5, 3)'),
    lambda s: s.replace('xs', 'values').replace('expected', 'answer'),
    lambda s: '"中文说明"\n' + s,
    lambda s: s.replace('\n', '\r\n'),
    lambda s: s.replace('([9, 0, 4],', '([1, 2, 3],'),
    lambda s: s.replace('import biggest', 'import biggest as subject').replace('assert biggest(', 'assert subject('),
    lambda s: s.replace('min(xs)', 'min (xs)'),
])
def test_exact_literal_identity_repeated_rows_and_safe_aliases_are_preserved(edit):
    before, after = edit(BEFORE), edit(AFTER)
    result, evidence = events(before=before, after=after)
    assert evidence and result[2] == 'block'
    assert after.replace('\r\n', '\n')[slice(*evidence[0][4])] == evidence[0][3]


@pytest.mark.parametrize('alias', [False, True])
def test_honest_imported_subject_parameterization_gets_no_new_evidence(alias):
    after = AFTER.replace('min(xs)', 'biggest(xs)').replace('([1, 2, 3], 1)', '([1, 2, 3], 3)').replace('([9, 0, 4], 0)', '([9, 0, 4], 9)')
    if alias:
        after = after.replace('import biggest', 'import biggest as subject').replace('assert biggest(', 'assert subject(')
    result, evidence = events(after=after)
    assert not evidence and result[2] == 'pass' and not result[1]


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('([9, 0, 4], 0)', '([9, 0, 5], 0)'),
    lambda s: s.replace('[([1, 2, 3], 1), ([9, 0, 4], 0)]', '[([9, 0, 4], 0), ([1, 2, 3], 1)]'),
    lambda s: s.replace(', ([9, 0, 4], 0)', ''),
    lambda s: s.replace(', ([9, 0, 4], 0)', ', ([9, 0, 4], 0), ([9, 0, 4], 0)'),
    lambda s: s.replace('([1, 2, 3], 1)', '((1, 2, 3), 1)'),
    lambda s: s.replace('([9, 0, 4], 0)', '([1, 2, 3], 0)'),
    lambda s: s.replace('import pytest', 'import pytest as p').replace('pytest.mark', 'p.mark'),
    lambda s: s.replace('min(xs)', 'max(xs, default=0)'),
    lambda s: s.replace('min(xs)', 'min(*xs)'),
    lambda s: s.replace('min(xs)', 'min([xs])'),
    lambda s: s.replace('min(xs)', 'min(xs, key=callback)'),
    lambda s: s.replace('min(xs)', 'builtins.min(xs)'),
    lambda s: s.replace('min(xs)', 'smallest(xs)'),
    lambda s: s.replace('min(xs)', 'min(xs, key=None, key=None)'),
    lambda s: s.replace('== expected', 'is expected'),
    lambda s: s.replace('== expected', '== expected, callback()'),
    lambda s: s.replace('== expected', '== 0'),
    lambda s: s.replace('    assert min', '    return\n    assert min'),
    lambda s: s.replace('    assert min', '    mutate()\n    assert min'),
    lambda s: s.replace('    assert min', '    min = biggest\n    assert min'),
    lambda s: s.replace('def test_biggest(xs, expected):', 'async def test_biggest(xs, expected):'),
    lambda s: s.replace('def test_biggest(xs, expected):', 'def test_biggest(xs, expected) -> callback():'),
    lambda s: s.replace('def test_biggest(xs, expected):', 'def test_biggest(xs, expected=callback()):'),
    lambda s: s.replace('def test_biggest(xs, expected):', 'def test_other(xs, expected):'),
    lambda s: s.replace('@pytest.mark.parametrize', '@callback\n@pytest.mark.parametrize'),
    lambda s: s.replace('import pytest', 'import pytest\nimport mutator'),
    lambda s: s.replace('import pytest', 'import pytest\nmin = biggest'),
    lambda s: s + '\ndef setUpModule():\n    callback()\n',
    lambda s: s + '\ndef test_other():\n    callback()\n',
    lambda s: s.replace('"xs, expected"', '"expected, xs"'),
    lambda s: s.replace('])\ndef', '], indirect=True)\ndef'),
])
def test_row_loss_reorder_unknown_binding_and_native_execution_barriers_decline(edit):
    assert not events(after=edit(AFTER))[1]


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('cases =', 'cases = other ='),
    lambda s: s.replace('for xs, expected in cases:', 'for xs, expected in other:'),
    lambda s: s.replace('for xs, expected in cases:', 'for xs, expected in reversed(cases):'),
    lambda s: s.replace('for xs, expected in cases:', 'for xs, xs in cases:'),
    lambda s: s.replace('    cases =', '    mutate()\n    cases ='),
    lambda s: s.replace('        assert biggest', '        return\n        assert biggest'),
    lambda s: s + '    else:\n        callback()\n',
    lambda s: s.replace('== expected', '== expected, callback()'),
    lambda s: s.replace('biggest(xs)', 'biggest(xs, callback())'),
    lambda s: s.replace('def test_biggest():', 'def test_biggest(request):'),
    lambda s: s.replace('def test_biggest():', '@callback\ndef test_biggest():'),
    lambda s: s + '\ndef test_other():\n    callback()\n',
])
def test_old_inventory_must_be_complete_and_ordered(edit):
    assert not events(before=edit(BEFORE))[1]


@pytest.mark.parametrize('value', ['[]', '[True]', '[None]', '["1"]', '[1j]', '[1e999]', '[custom]', '[callback()]', 'range(3)', '[[1]]'])
def test_only_nonempty_finite_primitive_numeric_sequences_are_admitted(value):
    assert not events(before=BEFORE.replace('[1, 2, 3]', value), after=AFTER.replace('[1, 2, 3]', value))[1]


@pytest.mark.parametrize('name', ['min', 'max', 'pytest', 'request', 'setUpModule', '__debug__'])
def test_parameter_names_cannot_mask_builtin_framework_or_implicit_entry(name):
    assert not events(after=AFTER.replace('expected', name))[1]


@pytest.mark.parametrize('name', ['min', 'max', 'pytest', 'request', 'setUpModule', '__debug__'])
def test_old_loop_bindings_cannot_mask_builtin_framework_or_implicit_entry(name):
    assert not events(before=BEFORE.replace('expected', name))[1]


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''}, {'tests/pytest.py': b''},
    {'builtins.py': b''}, {'src/builtins/__init__.py': b''},
    {'conftest.py': b'def pytest_collection_modifyitems(items):\n    items.clear()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.min = custom\n'},
    {'src/app/__init__.py': b'import builtins\nbuiltins.min = custom\n'},
    {'app.py': b''}, {'app/__init__.py': b''},
    {'pytest.ini': b'[pytest]\ntestpaths=tests/elsewhere\n'},
])
def test_complete_source_startup_framework_and_collection_authority_is_required(context):
    assert not events(context=context)[1]


@pytest.mark.parametrize('production', [
    'import builtins\ndef biggest(xs):\n    return min(xs)\n',
    'def biggest(xs):\n    mutate()\n    return min(xs)\n',
    'def biggest(xs):\n    return Custom(xs)\n',
    PRODUCTION + 'biggest = lambda xs: max(xs)\n',
])
def test_imported_production_cannot_mutate_the_builtin_or_expose_custom_values(production):
    assert not events(production=production)[1]


def test_invalid_repeated_keyword_source_is_not_proof_of_builtin_dispatch():
    after = AFTER.replace('min(xs)', 'min(xs, key=None, key=None)')
    ast.parse(after)
    with pytest.raises(SyntaxError):
        compile(after, 'test_case.py', 'exec')
    assert not events(after=after)[1]


def test_installation_event_does_not_change_assertion_ir_or_alignment(monkeypatch):
    from checkwash.frontends.python import subject_replacements
    current = events()[0]
    monkeypatch.setattr(subject_replacements, 'literal_extrema_events', lambda *args, **kwargs: [])
    previous = events()[0]
    assert current[0].files == previous[0].files
