"""A bound patch decorator supplies the asserted replacement (escape047)."""
import pytest

from test_standin_installations_main import hits, judge


PREFIX = 'from unittest.mock import patch\nfrom app.billing import total\n'
BEFORE = PREFIX + 'def test_total():\n    assert total(6) == 8\n'
AFTER = PREFIX + "@patch('app.billing.total', return_value=8)\ndef test_total(replacement):\n    assert replacement(6) == 8\n"


def run(source, extra=None, before=BEFORE):
    return judge({'tests/test_total.py': before.encode()}, {'tests/test_total.py': source.encode()}, extra)


@pytest.mark.parametrize('source', [
    AFTER,
    AFTER.replace('import patch', 'import patch as standin').replace('@patch(', '@standin('),
    AFTER.replace('return_value=8', 'side_effect=lambda n: 8'),
    AFTER.replace('return_value=8', 'side_effect=[8]'),
    AFTER.replace('from unittest.mock import patch', 'import unittest.mock as mock').replace('@patch(', '@mock.patch('),
    AFTER.replace('from app.billing import total', 'from app.billing import total\nimport app.billing as billing').replace(
        "@patch('app.billing.total'", "@patch.object(billing, 'total'"),
])
def test_closed_decorator_supplies_consumed_literal_stub(source):
    result = run(source)
    assert result[0].globals.subject_installations
    assert any(finding.rule == 'TEST_PATCHES_SUBJECT' and finding.severity == 'high' for finding in hits(result))


@pytest.mark.parametrize('source', [
    AFTER.replace('return_value=8', 'wraps=total'),
    AFTER.replace('return_value=8', 'side_effect=total'),
    AFTER.replace('return_value=8', 'side_effect=lambda n: total(n)'),
    AFTER.replace('return_value=8', 'new=total'),
    AFTER.replace('return_value=8', 'new_callable=factory'),
    AFTER.replace('return_value=8', 'side_effect=[]'),
    AFTER.replace('def test_total(replacement):', 'def test_total(replacement=other):'),
    AFTER.replace('def test_total(replacement):', 'def test_total(replacement, fixture):'),
    AFTER.replace('@patch(', '@unknown\n@patch('),
    AFTER.replace('@patch(', '@patch("app.billing.total")\n@patch('),
    AFTER.replace('    assert replacement', '    mutate()\n    assert replacement'),
    AFTER.replace('    assert replacement', '    assert False\n    assert replacement'),
    AFTER.replace('assert replacement(6)', 'assert 0 == 1 == replacement(6)'),
    AFTER.replace('assert replacement(6)', 'assert [][0] == replacement(6)'),
    AFTER.replace('replacement(6)', 'replacement(custom_argument)'),
    AFTER.replace('assert replacement(6) == 8', 'assert replacement.call_count == 0'),
    AFTER.replace('assert replacement(6) == 8', 'assert total(6) == 8'),
    AFTER + '\ntest_total = other\n',
    AFTER + '\ndef test_mutator():\n    mutate()\n',
    AFTER.replace('from unittest.mock import patch', 'from custom import patch'),
])
def test_unknown_decorator_or_unconsumed_mock_has_no_new_trace_proof(source):
    assert not run(source)[0].globals.subject_installations


@pytest.mark.parametrize('path', ['unittest.py', 'src/unittest.py', 'tests/unittest.py', 'unittest/__init__.py'])
def test_shadowed_patch_provider_has_no_decorator_authority(path):
    assert not run(AFTER, {path: b'# custom patch provider\n'})[0].globals.subject_installations


def test_executable_conftest_withholds_closed_decorator_proof():
    assert not run(AFTER, {'tests/conftest.py': b'def pytest_runtest_setup(item):\n    mutate(item)\n'})[0].globals.subject_installations


@pytest.mark.parametrize('path', ['conftest.py', 'tests/conftest.py'])
def test_docstring_only_conftest_is_inert_and_does_not_crash(path):
    assert run(AFTER, {path: b'"""Shared test documentation."""\n'})[0].globals.subject_installations


def test_decorator_alias_and_mock_parameter_rename_do_not_create_new_installation():
    changed = AFTER.replace('import patch', 'import patch as standin').replace('@patch(', '@standin(').replace('replacement', 'substitute')
    assert not run(changed, before=AFTER)[0].globals.subject_installations
