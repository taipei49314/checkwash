"""Imported production must not supply a counterfeit stdlib patch API."""
import pytest

from test_patch_decorator_consumers import AFTER as DECORATOR, run
from test_patch_call_record_consumers import AFTER as RECORD


@pytest.mark.parametrize('source', [DECORATOR, RECORD,
    RECORD.replace("patch('app.billing.total'", "patch.object(total, '__call__'")])
@pytest.mark.parametrize('extra', [
    {'app/billing.py': b'import unittest.mock\ndef total(n):\n    return 8\nunittest.mock.patch=total\n'},
    {'app/__init__.py': b'import unittest.mock\nfrom .billing import total\nunittest.mock.patch=total\n'},
    {'tests/__init__.py': b'import unittest.mock\nfrom app.billing import total\nunittest.mock.patch=total\n'},
    {'tests/conftest.py': b'def pytest_configure():\n    import unittest.mock\n    unittest.mock.patch=lambda *a, **k: None\n'},
    {'tests/test_aaa.py': b'import unittest.mock\nunittest.mock.patch=lambda *a, **k: None\n'},
    {'pytest.ini': b'[pytest]\naddopts=-p mutator\n'},
])
def test_production_packages_and_test_startup_may_replace_patch(source, extra):
    # Existing patch rules retain their contract. This checks only the new
    # assertion/call-record consumption evidence.
    assert not run(source, extra)[0].globals.subject_installations


@pytest.mark.parametrize('source', [DECORATOR, RECORD])
def test_arbitrary_import_does_not_borrow_target_purity(source):
    source = source.replace('from app.billing import total', 'from app.billing import total\nimport mutator')
    assert not run(source, {'mutator.py': b'import unittest.mock\nunittest.mock.patch=None\n'})[0].globals.subject_installations


def test_counterfeit_patch_decorator_forwards_the_real_production():
    calls = []
    def total(n):
        calls.append(n)
        return 8
    def fake_patch(*args, **kwargs):
        def decorate(function):
            return lambda: function(total)
        return decorate
    namespace = {'total': total, 'patch': fake_patch}
    source = DECORATOR.replace('from app.billing import total\n', '').replace('from unittest.mock import patch\n', '')
    exec(source, namespace)
    namespace['test_total']()
    assert calls == [6]
    production = b'''import unittest.mock
def total(n):
    return 8
def fake_patch(*args, **kwargs):
    def decorate(function):
        return lambda: function(total)
    return decorate
unittest.mock.patch = fake_patch
'''
    assert not run(DECORATOR, {'app/billing.py': production})[0].globals.subject_installations
