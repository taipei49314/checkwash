"""A closed local implementation cannot replace the imported tested provider."""
import pytest

from checkwash import engine
from test_issue_expectation_families import run

PRODUCTION = '''def percent(n, total):
    if total == 0:
        return 0
    return round(n / total)
'''
BEFORE = '''from app.prod import percent
def test_quarter():
    assert percent(1, 4) == 25
def test_half():
    assert percent(1, 2) == 50
def test_all():
    assert percent(3, 3) == 100
'''
HELPER = '''def calculate_percentage(n, total):
    if total == 0:
        return 0
    return round(n / total * 100)
'''
AFTER = '''import pytest
from app.prod import percent
''' + HELPER + '''
@pytest.mark.parametrize("n,total,expected", [(1, 4, 25), (1, 2, 50), (3, 3, 100)])
def test_percent(n, total, expected):
    assert calculate_percentage(n, total) == expected
'''


def installations(result):
    return result[0].globals.subject_installations


@pytest.mark.parametrize('after', [AFTER,
    AFTER.replace('calculate_percentage','local_percent'),
    AFTER.replace('return round(n / total * 100)', 'return round(round(n / total * 100))'),
    AFTER.replace('if total == 0:', 'if total <= 0:'),
    AFTER.replace('    if total == 0:\n        return 0\n', ''),
    AFTER.replace('return round(n / total * 100)', 'return 0'),
])
def test_closed_local_subject_replacement_adds_existing_installation_evidence(after):
    result = run(BEFORE, after, PRODUCTION)
    assert result[2] == 'block' and len(installations(result)) == 1
    path, unit, target, text, span = installations(result)[0]
    assert (path, unit, target) == ('tests/test_case.py', 'test_percent', 'app.prod.percent')
    assert after[slice(*span)] == text
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' and f.severity == 'high' for f in result[1])


def test_assertion_ir_and_alignment_are_unchanged(monkeypatch):
    current = run(BEFORE, AFTER, PRODUCTION)
    monkeypatch.setattr(engine, 'local_parameter_implementation_events', lambda *args, **kwargs: [])
    prior = run(BEFORE, AFTER, PRODUCTION)
    assert current[0].files == prior[0].files


@pytest.mark.parametrize('after', [
    AFTER.replace(HELPER, 'def calculate_percentage(n, total):\n    return percent(n, total)\n'),
    AFTER.replace(HELPER, '').replace('import percent', 'import percent as calculate_percentage'),
    AFTER.replace('from app.prod import percent', 'from app.prod import percent as imported_percent').replace(
        HELPER, 'def calculate_percentage(n, total):\n    return imported_percent(n, total)\n'),
    AFTER.replace('return round(n / total * 100)', 'return percent(n, total)'),
    AFTER.replace('return round(n / total * 100)', 'return round(percent(n, total))'),
])
@pytest.mark.parametrize('production', [PRODUCTION, PRODUCTION.replace('round(n / total)', 'round(n / total * 100)')])
def test_forwarders_and_renamed_imports_never_become_local_standin_evidence(after, production):
    assert not installations(run(BEFORE, after, production))


@pytest.mark.parametrize('after', [
    AFTER.replace('(1, 4, 25)', '(1, 4, 24)'),
    AFTER.replace('(1, 4, 25)', '(2, 4, 25)'),
    AFTER.replace('(1, 4, 25), (1, 2, 50)', '(1, 2, 50), (1, 4, 25)'),
    AFTER.replace(', (3, 3, 100)', ''),
    AFTER.replace('(3, 3, 100)', '(3, 3, 100), (3, 3, 100)'),
    AFTER.replace('(1, 4, 25)', '(True, 4, 25)'),
    AFTER.replace('(1, 4, 25)', '(1e999, 4, 25)'),
    AFTER.replace('(1, 4, 25)', 'pytest.param(1, 4, 25, marks=pytest.mark.skip)'),
    AFTER.replace('])', '], indirect=True)'),
    AFTER.replace('])', '], ids=callback)'),
    AFTER.replace('"n,total,expected"', '"n,total,request"'),
    AFTER.replace('n, total, expected):', 'n, total, total):'),
    AFTER.replace('def test_percent(n, total, expected):', 'def test_percent(n, total, expected=callback()):'),
    AFTER.replace('def test_percent(n, total, expected):', 'def test_percent(n: callback(), total, expected):'),
    AFTER.replace('def test_percent(n, total, expected):', '@pytest.mark.skip\ndef test_percent(n, total, expected):'),
    AFTER.replace('calculate_percentage(n, total) == expected', 'calculate_percentage(total, n) == expected'),
    AFTER.replace('calculate_percentage(n, total) == expected', 'calculate_percentage(n, total=total) == expected'),
    AFTER.replace('calculate_percentage(n, total) == expected', 'calculate_percentage(n, total) is expected'),
    AFTER.replace('calculate_percentage(n, total) == expected', 'calculate_percentage(n, total) == expected, callback()'),
    AFTER.replace('    assert calculate_percentage', '    mutate()\n    assert calculate_percentage'),
    AFTER.replace('    assert calculate_percentage', '    assert False\n    assert calculate_percentage'),
    AFTER + '\ndef test_other():\n    mutate()\n',
    AFTER + '\ncalculate_percentage = percent\n',
])
def test_complete_parameter_inventory_and_collected_binding_are_required(after):
    assert not installations(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('def calculate_percentage(n, total):', '@decorate\ndef calculate_percentage(n, total):'),
    AFTER.replace('def calculate_percentage(n, total):', 'def calculate_percentage(n, total=callback()):'),
    AFTER.replace('def calculate_percentage(n, total):', 'def calculate_percentage(n, total) -> callback():'),
    AFTER.replace('def calculate_percentage(n, total):', 'def calculate_percentage(n, round):'),
    AFTER.replace('    if total == 0:', '    mutate()\n    if total == 0:'),
    AFTER.replace('total == 0', 'external == 0'),
    AFTER.replace('return 0', 'return callback()'),
    AFTER.replace('return round(n / total * 100)', 'return callback(n, total)'),
    AFTER.replace('return round(n / total * 100)', 'return round(n / (total - total))'),
    AFTER.replace('return round(n / total * 100)', 'return round(n / (n - 3))'),
    AFTER.replace('return round(n / total * 100)', 'return [n, total]'),
    AFTER.replace('return round(n / total * 100)', 'return round(n / total, 2)'),
    AFTER.replace('return round(n / total * 100)', 'return round(number=n / total)'),
    AFTER.replace('return round(n / total * 100)', 'return n ** total'),
    AFTER.replace('return round(n / total * 100)', 'return n.__class__'),
    AFTER.replace('return round(n / total * 100)', 'return round(n / total * 1e999)'),
    AFTER.replace('return round(n / total * 100)', 'yield round(n / total * 100)'),
])
def test_only_a_closed_terminating_numeric_helper_supplies_the_standin(after):
    assert not installations(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('before', [
    BEFORE.replace('assert percent(1, 4) == 25', 'assert percent(1, 4) == 25, callback()'),
    BEFORE.replace('assert percent(1, 4) == 25', 'assert percent(n=1, total=4) == 25'),
    BEFORE.replace('def test_quarter():', 'def test_quarter(request):'),
    BEFORE.replace('    assert percent(1, 4)', '    mutate()\n    assert percent(1, 4)'),
    BEFORE + '\npercent = other\n',
    'import external\n' + BEFORE,
])
def test_original_subject_calls_must_have_closed_authority(before):
    assert not installations(run(before, AFTER, PRODUCTION))


@pytest.mark.parametrize('production', ['def percent(n,total):\n    return Custom()\n',
    'def percent(n,total):\n    mutate()\n    return 0\n',
    'import builtins\nbuiltins.round = callback\n' + PRODUCTION,
    'from tests.test_case import calculate_percentage\n' + PRODUCTION,
])
def test_imported_production_cannot_install_or_mutate_the_local_helper(production):
    assert not installations(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('context', [
    {'app/__init__.py': b''}, {'app.py': b''}, {'tests/app/__init__.py': b''},
    {'pytest.py': b''}, {'src/pytest.py': b''},
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.round = callback\n'},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/test_aaa.py': b'import tests.test_case\ntests.test_case.calculate_percentage = other\n'},
])
def test_framework_startup_siblings_and_import_roots_are_closed(context):
    assert not installations(run(BEFORE, AFTER, PRODUCTION, context=context))
