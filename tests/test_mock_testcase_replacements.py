"""Complete old oracle rows remain identifiable across mocked TestCase moves."""
import pytest

from test_standin_installations_main import hits, judge


BEFORE = '''from app.billing import total
def test_first():
    assert total("a") == "A"
def test_second():
    assert total("b") == "B"
'''
AFTER = '''import unittest
from unittest.mock import patch
from app.billing import total
class TestTotal(unittest.TestCase):
    @patch('app.billing.total', side_effect=['A', 'B'])
    def test_values(self, replacement):
        assert replacement("a") == "A"
        assert replacement("b") == "B"
if __name__ == '__main__':
    unittest.main()
'''


def run(source, extra=None, before=BEFORE):
    return judge({'tests/test_total.py': before.encode()}, {'tests/test_total.py': source.encode()}, extra)


@pytest.mark.parametrize('source', [
    AFTER,
    AFTER.replace('import unittest', 'import unittest as ut').replace('unittest.TestCase', 'ut.TestCase').replace('unittest.main()', 'ut.main()'),
    AFTER.replace('import patch', 'import patch as standin').replace('@patch(', '@standin(').replace('replacement', 'substitute'),
    AFTER.replace('import unittest', 'from unittest import TestCase, main').replace('unittest.TestCase', 'TestCase').replace('unittest.main()', 'main()'),
])
def test_full_preserved_inventory_moved_into_mocked_testcase_blocks(source):
    result = run(source)
    assert len(result[0].globals.subject_installations) == 1
    assert any(finding.severity == 'high' and finding.unit == 'TestTotal.test_values' for finding in hits(result))


@pytest.mark.parametrize('source', [
    AFTER.replace('unittest.TestCase', 'CustomCase'),
    AFTER.replace('class TestTotal', '@decorate\nclass TestTotal'),
    AFTER.replace('class TestTotal(unittest.TestCase):', 'class TestTotal(unittest.TestCase, metaclass=Meta):'),
    AFTER.replace('    @patch', '    def setUp(self):\n        mutate()\n    @patch'),
    AFTER.replace('    @patch', '    @decorate\n    @patch'),
    AFTER.replace("side_effect=['A', 'B']", 'wraps=total'),
    AFTER.replace("side_effect=['A', 'B']", 'side_effect=total'),
    AFTER.replace("side_effect=['A', 'B']", "side_effect=['A']"),
    AFTER.replace("side_effect=['A', 'B']", "side_effect=['B', 'A']"),
    AFTER.replace('replacement("b")', 'replacement("c")'),
    AFTER.replace('== "B"', '== "C"'),
    AFTER.replace('        assert replacement("b") == "B"\n', ''),
    AFTER.replace('        assert replacement("a") == "A"', '        assert False\n        assert replacement("a") == "A"'),
    AFTER.replace('        assert replacement("a") == "A"', '        assert 0 == 1 == replacement("a") == "A"'),
    AFTER.replace('        assert replacement("a") == "A"', '        if enabled:\n            assert replacement("a") == "A"'),
    AFTER.replace('def test_values(self, replacement):', 'def test_values(self, replacement=other):'),
    AFTER.replace('def test_values(self, replacement):', 'def test_values(self, replacement, fixture):'),
    AFTER.replace('unittest.main()', 'mutate()'),
    AFTER.replace("if __name__ == '__main__':", 'if enabled:'),
    AFTER + '\nTestTotal.test_values = other\n',
    AFTER.replace('import unittest', 'import unittest\nimport unknown'),
])
def test_partial_dynamic_or_custom_dispatch_never_proves_existing_oracle_mapping(source):
    assert not run(source)[0].globals.subject_installations


@pytest.mark.parametrize('extra', [
    {'unittest.py': b'# custom provider\n'}, {'src/unittest.py': b'# custom provider\n'},
    {'tests/unittest.py': b'# custom provider\n'},
    {'conftest.py': b'def pytest_runtest_setup(item):\n    mutate(item)\n'},
])
def test_library_shadow_and_executable_startup_withhold_testcase_proof(extra):
    assert not run(AFTER, extra)[0].globals.subject_installations


def test_unknown_old_tests_and_added_or_removed_tests_cannot_supply_complete_mapping():
    for before in (BEFORE.replace('def test_first():', '@decorate\ndef test_first():'),
                   BEFORE + 'def test_extra():\n    assert total("c") == "C"\n',
                   BEFORE.replace('    assert total("b") == "B"', '    assert total(value) == "B"')):
        assert not run(AFTER, before=before)[0].globals.subject_installations


@pytest.mark.parametrize('extra', [
    {'app/billing.py': b'import unittest\ndef total(value):\n    return value.upper()\nunittest.TestCase.run=total\n'},
    {'app/billing.py': b'import unittest.mock\ndef total(value):\n    return value.upper()\nunittest.mock.patch=total\n'},
    {'app/__init__.py': b'import unittest.mock\nfrom .billing import total\nunittest.mock.patch=total\n'},
    {'tests/test_aaa.py': b'import unittest.mock\nfrom app.billing import total\nunittest.mock.patch=total\n'},
    {'tests/__init__.py': b'import unittest\nunittest.TestCase.run=lambda self: None\n'},
    {'pytest.ini': b'[pytest]\naddopts=-p mutator\n'},
])
def test_imported_source_and_startup_cannot_supply_custom_dispatch(extra):
    assert not run(AFTER, extra)[0].globals.subject_installations


def test_extra_production_import_is_not_covered_by_subject_function_purity():
    after = AFTER.replace('from app.billing import total', 'from app.billing import total, mutate')
    assert not run(after)[0].globals.subject_installations


def test_old_unknown_import_cannot_establish_original_production_binding():
    before = BEFORE.replace('from app.billing import total', 'import mutator\nfrom app.billing import total')
    assert not run(AFTER, before=before)[0].globals.subject_installations


def test_removed_old_sibling_remains_in_original_provider_authority_inventory():
    before = {'tests/test_total.py': BEFORE.encode(),
              'tests/test_aaa.py': b'import unittest.mock\nfrom app.billing import total\nunittest.mock.patch=total\n'}
    after = {'tests/test_total.py': AFTER.encode()}
    assert not judge(before, after)[0].globals.subject_installations


def test_added_inert_sibling_does_not_invent_a_missing_old_source():
    before = {'tests/test_total.py': BEFORE.encode()}
    after = {'tests/test_total.py': AFTER.encode(), 'tests/test_aaa.py': b'def test_padding():\n    assert True\n'}
    assert judge(before, after)[0].globals.subject_installations
