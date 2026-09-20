"""An introduced empty parameter set removes the original ordinary test."""
import pytest

from test_issue_expectation_families import run


BEFORE = 'from app.prod import double\ndef test_double():\n    assert double(2) == 4\n'
AFTER = '''import pytest
from app.prod import double
@pytest.mark.parametrize('_unused', [])
def test_double(_unused):
    assert double(2) == 4
'''
PROD = 'def double(x):\n    return x + x - 1\n'


@pytest.mark.parametrize('rows', ['[]', '()', 'list()', 'tuple()', 'range(0)', 'list(())',
                                 '[x for x in [] if x]', '(x for x in ())',
                                 '[callback(x) for x in [] if callback(x)]'])
def test_new_empty_set_is_a_known_single_case_loss(rows):
    ir, findings, verdict = run(BEFORE, AFTER.replace('[]', rows), PROD)
    assert verdict == 'block'
    assert any(f.rule == 'TEST_DISABLED' and f.shape == 'param_cases_removed' for f in findings)
    units = [unit for file in ir.files for unit in file.units if unit.qualname == 'test_double']
    assert units[0].before.param_cases == 1 and units[0].after.param_cases == 0


@pytest.mark.parametrize('rows', ['[1]', '[x for x in [1] if False]', 'provider()', 'range(value)', '[] + []'])
def test_nonempty_or_unproved_provider_has_no_new_count_proof(rows):
    ir, _, _ = run(BEFORE, AFTER.replace('[]', rows), PROD)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


@pytest.mark.parametrize('before,after', [
    (AFTER.replace('[]', 'provider()'), AFTER),
    (BEFORE.replace('test_double():', 'test_double(request):'), AFTER),
    ('@decorate\n' + BEFORE, AFTER),
    (BEFORE, AFTER.replace("'_unused', []", "'_unused', [], ids=callback")),
    (BEFORE, AFTER.replace('import pytest', 'import custom as pytest')),
    (BEFORE, AFTER.replace('import pytest', 'import pytest\ndef list():\n    return [1]').replace('[]', 'list()')),
    (BEFORE, AFTER.replace('import pytest', 'import pytest\npytest = custom')),
    (BEFORE, AFTER.replace('test_double(_unused):', 'test_double(_unused=1):')),
    (BEFORE, AFTER + '\ndef pytest_generate_tests(metafunc):\n    mutate(metafunc)\n'),
    (BEFORE, AFTER.replace('[]', '[x for x in [] async for y in other]')),
    (BEFORE, AFTER.replace('import pytest\n', '') + '\nimport pytest\n'),
])
def test_ambiguous_previous_collection_or_decorator_authority_is_not_assumed(before, after):
    ir, _, _ = run(before, after, PROD)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


@pytest.mark.parametrize('context', [
    {'pytest.py': b'def mark():\n    pass\n'},
    {'tests/conftest.py': b'def pytest_collection_modifyitems(items):\n    items.clear()\n'},
    {'src/app/__init__.py': b'import pytest\npytest.mark.parametrize = other\n'},
    {'app/__init__.py': b'import pytest\npytest.mark.parametrize = other\n'},
    {'src/app.py': b''},
])
def test_repository_startup_cannot_mint_empty_collection_authority(context):
    ir, _, _ = run(BEFORE, AFTER, PROD, context=context)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


def test_unknown_production_import_effects_withhold_collection_count():
    production = 'import pytest\npytest.mark.parametrize = other\ndef double(x):\n    return x+x\n'
    ir, _, _ = run(BEFORE, AFTER, production)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


def test_plain_function_body_does_not_execute_during_collection():
    production = 'def double(x):\n    return f"{x}..{x}"\n'
    _, findings, verdict = run(BEFORE, AFTER, production)
    assert verdict == 'block' and any(f.rule == 'TEST_DISABLED' for f in findings)


@pytest.mark.parametrize('production', [
    '@decorate\ndef double(x):\n    return x\n',
    'def double(x=callback()):\n    return x\n',
    'def double(x: callback()):\n    return x\n',
    'import mutator\ndef double(x):\n    return x\n',
])
def test_evaluated_signatures_and_imports_are_not_inert(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)
