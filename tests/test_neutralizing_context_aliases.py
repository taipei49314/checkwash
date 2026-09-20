"""Closed callable aliases retain the ordinary assertion-swallowing signal."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def is_success(code):\n    return code in (200, 201, 204)\n'
BEFORE = '''from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    assert is_success(201) == False
'''
AFTER = '''from app.prod import is_success
import pytest
_r = pytest.raises
def test_only_200():
    assert is_success(200) == True
    with _r(AssertionError):
        assert is_success(201) == False
'''


def alias_contexts(before=BEFORE, after=AFTER, production=PRODUCTION, *, context=None):
    result = run(before, after, production, context=context)
    return result, [text for _, text in result[0].globals.broad_excepts_added if text.startswith(('_r(', '_s('))]


@pytest.mark.parametrize('after', [
    AFTER,
    AFTER.replace('import pytest', 'import pytest as p').replace('= pytest.raises', '= p.raises'),
    AFTER.replace('import pytest\n_r = pytest.raises', 'from pytest import raises\n_r = raises'),
    AFTER.replace('import pytest\n_r = pytest.raises', 'from pytest import raises as raises_error\n_r = raises_error'),
    AFTER.replace('_r = pytest.raises', '_first = pytest.raises\n_r = _first'),
    AFTER.replace('AssertionError', 'Exception'),
    AFTER.replace('AssertionError', 'BaseException'),
    AFTER.replace('AssertionError', '(ValueError, AssertionError)'),
    AFTER.replace('import pytest\n_r = pytest.raises', 'import contextlib\n_r = contextlib.suppress'),
    AFTER.replace('import pytest\n_r = pytest.raises', 'from contextlib import suppress as s\n_r = s'),
    AFTER.replace('import pytest\n_r = pytest.raises', 'import contextlib\n_r = contextlib.suppress').replace('AssertionError)', 'ValueError, AssertionError)'),
])
def test_closed_single_definition_callable_aliases_retain_catcher_evidence(after):
    result, contexts = alias_contexts(after=after)
    assert contexts and result[2] == 'block'
    assert any(finding.rule == 'BROAD_EXCEPT_ADDED' and finding.severity == 'high' for finding in result[1])
    assert all(context in after.replace(' ', '') for context in contexts)


def test_identical_prior_assertions_and_order_are_preserved():
    result, contexts = alias_contexts()
    unit = result[0].files[0].units[0]
    assert len(unit.before.assertions) == len(unit.after.assertions) == 2
    assert contexts == ['_r(AssertionError)']


def test_two_new_contexts_preserve_multiplicity():
    after = AFTER.replace('    assert is_success(200) == True', '    with _r(AssertionError):\n        assert is_success(200) == True')
    _, contexts = alias_contexts(after=after)
    assert contexts == ['_r(AssertionError)', '_r(AssertionError)']


@pytest.mark.parametrize('after', [
    AFTER.replace('_r = pytest.raises', '_r = custom'),
    AFTER.replace('_r = pytest.raises', '_r = factory()'),
    AFTER.replace('_r = pytest.raises', '_r = pytest.raises\n_r = custom'),
    AFTER.replace('_r = pytest.raises', '_r = pytest.raises\ndel _r'),
    AFTER.replace('_r = pytest.raises', 'if flag:\n    _r = pytest.raises'),
    AFTER.replace('_r = pytest.raises', '_r: object = pytest.raises'),
    AFTER.replace('_r = pytest.raises', '_r = other = pytest.raises'),
    AFTER.replace('_r = pytest.raises', '_r = forward\nforward = pytest.raises'),
    AFTER.replace('_r = pytest.raises', '_r = pytest.raises\npytest.raises = custom'),
    AFTER.replace('_r = pytest.raises', '_r = pytest.raises\nAssertionError = ValueError'),
    AFTER.replace('from app.prod import is_success', 'from app.prod import is_success\nfrom other import callback'),
    AFTER.replace('from app.prod import is_success', 'from app.prod import is_success\nimport mutator'),
    AFTER.replace('def test_only_200():', 'def test_only_200(_r):'),
    AFTER.replace('def test_only_200():', 'def test_only_200(_r=pytest.raises):'),
    AFTER.replace('def test_only_200():', '@decorate\ndef test_only_200():'),
    AFTER.replace('def test_only_200():', 'async def test_only_200():'),
    AFTER.replace('    with _r', '    _r = custom\n    with _r'),
    AFTER.replace('    with _r', '    globals()["_r"] = custom\n    with _r'),
    AFTER.replace('    with _r', '    assert False\n    with _r'),
    AFTER.replace('    with _r', '    return\n    with _r'),
    AFTER.replace('    with _r', '    mutate()\n    with _r'),
    AFTER + '\ndef test_other():\n    mutate()\n',
    AFTER + '\n_r = custom\n',
])
def test_uncertain_binding_execution_and_extra_callbacks_withhold_new_proof(after):
    assert not alias_contexts(after=after)[1]


@pytest.mark.parametrize('after', [
    AFTER.replace('AssertionError', 'ValueError'),
    AFTER.replace('AssertionError', 'E'),
    AFTER.replace('_r(AssertionError)', '_r()'),
    AFTER.replace('_r(AssertionError)', '_r(AssertionError, callback)'),
    AFTER.replace('_r(AssertionError)', '_r(AssertionError, match="boom")'),
    AFTER.replace('_r(AssertionError)', '_r((AssertionError, callback()))'),
    AFTER.replace('_r(AssertionError)', '_r((AssertionError, (ValueError,)))'),
    AFTER.replace('_r(AssertionError):', '_r(AssertionError) as caught:'),
    AFTER.replace('_r(AssertionError):', '_r(AssertionError), callback():'),
    AFTER.replace('        assert is_success(201) == False', '        validator()'),
    AFTER.replace('        assert is_success(201) == False', '        def unused():\n            assert is_success(201) == False'),
    AFTER.replace('        assert is_success(201) == False', '        if flag:\n            assert is_success(201) == False'),
    AFTER.replace('== False', '== True'),
    AFTER.replace('is_success(201)', 'is_success(202)'),
    AFTER.replace('is_success(201)', 'is_success(value)'),
    AFTER.replace('is_success(201)', 'is_success(callback())'),
    AFTER.replace('== False', '== expected'),
    AFTER.replace('== False', '== False, callback()'),
    AFTER.replace('    assert is_success(200) == True\n', ''),
])
def test_only_preserved_direct_assertions_in_a_known_broad_catcher_qualify(after):
    assert not alias_contexts(after=after)[1]


def test_existing_context_alias_is_not_an_introduction():
    result, contexts = alias_contexts(before=AFTER, after=AFTER.replace('_r = pytest.raises', '_first = pytest.raises\n_r = _first'))
    assert not contexts and result[2] == 'pass'


def test_repeated_keyword_source_error_cannot_prove_assertion_consumption():
    before = BEFORE.replace('is_success(201)', 'is_success(code=201, code=201)')
    after = AFTER.replace('is_success(201)', 'is_success(code=201, code=201)')
    for source in (before, after):
        with pytest.raises(SyntaxError, match='keyword argument repeated'):
            compile(source, '<invalid-test>', 'exec')
    assert not alias_contexts(before=before, after=after)[1]


@pytest.mark.parametrize('production', [
    'import mutator\n' + PRODUCTION,
    'import pytest\npytest.raises = custom\n' + PRODUCTION,
    'import builtins\nbuiltins.AssertionError = ValueError\n' + PRODUCTION,
    'def is_success(code):\n    mutate()\n    return code == 200\n',
    'def is_success(code):\n    return Custom(code)\n',
])
def test_complete_imported_production_must_be_primitive_and_inert(production):
    assert not alias_contexts(production=production)[1]


@pytest.mark.parametrize('context', [
    {'app/__init__.py': b''},
    {'app.py': b''},
    {'tests/app/__init__.py': b''},
    {'pytest.py': b''},
    {'src/pytest/__init__.py': b''},
    {'tests/pytest.py': b''},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/conftest.py': b'import pytest\npytest.raises = custom\n'},
    {'tests/test_earlier.py': b'import pytest\npytest.raises = custom\n'},
    {'pytest.ini': b'[pytest]\naddopts = -p plugin\n'},
])
def test_repository_import_roots_and_startup_sources_must_be_closed(context):
    assert not alias_contexts(context=context)[1]


def test_contextlib_shadow_withholds_its_alias_proof():
    after = AFTER.replace('import pytest\n_r = pytest.raises', 'import contextlib\n_r = contextlib.suppress')
    assert not alias_contexts(after=after, context={'src/contextlib.py': b''})[1]


@pytest.mark.parametrize('name', ['setUpModule', 'tearDownModule', 'setUpClass', 'tearDownClass',
                                'setUp', 'tearDown', 'setup_module', 'pytestmark'])
@pytest.mark.parametrize('binding', ['production', 'standard_module'])
def test_implicit_framework_names_cannot_supply_subject_or_catcher_authority(name, binding):
    if binding == 'production':
        def renamed(source):
            return source.replace('import is_success', f'import is_success as {name}').replace('assert is_success(', f'assert {name}(')
        before, after = renamed(BEFORE), renamed(AFTER)
    else:
        before = BEFORE
        after = AFTER.replace('import pytest', f'import pytest as {name}').replace('= pytest.raises', f'= {name}.raises')
    assert not alias_contexts(before=before, after=after)[1]


def test_absent_strict_snapshot_reader_does_not_extend_legacy_dynamic_resolution():
    from test_neutralization_matrix import _run
    verdict, findings = _run(BEFORE, AFTER)
    assert verdict == 'pass' and not any(f.rule == 'BROAD_EXCEPT_ADDED' for f in findings)
