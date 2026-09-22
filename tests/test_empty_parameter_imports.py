"""Collection counts require import-time inertness, not pure test execution."""
import pytest

from test_empty_parameter_introduction import BEFORE, AFTER, PROD
from test_issue_expectation_families import run


@pytest.mark.parametrize('extra', [
    'import unittest\n', 'import sys\n', 'import os\n', 'import os as operating_system\n',
    'from typing import TYPE_CHECKING\n', 'from contextlib import suppress as quiet\n',
])
def test_standard_imports_allow_the_same_closed_empty_collection(extra):
    ir, findings, verdict = run(extra + BEFORE, extra + AFTER, PROD)
    assert verdict == 'block'
    assert any(f.rule == 'TEST_DISABLED' and f.shape == 'param_cases_removed' for f in findings)


@pytest.mark.parametrize('module,extra', [
    ('unittest', 'import unittest\n'), ('sys', 'import sys\n'), ('os', 'import os\n'),
    ('typing', 'from typing import TYPE_CHECKING\n'),
    ('contextlib', 'from contextlib import suppress as quiet\n'),
])
@pytest.mark.parametrize('prefix,suffix', [('', '.py'), ('src/', '/__init__.py'), ('tests/', '.py')])
def test_repository_standard_module_shadow_withholds_proof(module, extra, prefix, suffix):
    context = {prefix + module + suffix: b'import pytest\npytest.mark.parametrize = lambda *a: lambda f: f\n'}
    ir, _, _ = run(extra + BEFORE, extra + AFTER, PROD, context=context)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


@pytest.mark.parametrize('extra', ['import os as pytest\n', 'from typing import TYPE_CHECKING as pytestmark\n',
                                 'import unittest as setup_module\n', 'from contextlib import ExitStack\n'])
def test_standard_imports_do_not_hide_controls_or_unknown_symbols(extra):
    ir, _, _ = run(extra + BEFORE, extra + AFTER, PROD)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


def test_inert_class_definition_does_not_run_methods_at_import():
    production = '''class double:
    def __init__(self, x):
        self.value = callback(x)
    def __eq__(self, other):
        return callback(other)
'''
    _, findings, verdict = run(BEFORE, AFTER, production)
    assert verdict == 'block' and any(f.rule == 'TEST_DISABLED' for f in findings)


@pytest.mark.parametrize('production', [
    'class double(callback()):\n    pass\n',
    'class double(metaclass=custom):\n    pass\n',
    '@decorate\nclass double:\n    pass\n',
    'class double:\n    result = callback()\n',
    'class double:\n    @decorate\n    def run(self):\n        pass\n',
    'class double:\n    def run(self, x=callback()):\n        pass\n',
    'class double:\n    def run(self, x: callback()):\n        pass\n',
    'class double:\n    def run(self):\n        pass\n    def run(self):\n        pass\n',
    'class double:\n    def __slots__(self):\n        pass\n',
    'class double:\n    def __qualname__(self):\n        pass\n',
    'class double:\n    def __classcell__(self):\n        pass\n',
])
def test_class_creation_effects_are_not_treated_as_inert(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)


def test_introduced_async_body_is_also_unexecuted_for_empty_parameters():
    ir, findings, verdict = run(BEFORE, AFTER.replace('def test_double', 'async def test_double'), PROD)
    assert verdict == 'block'
    assert any(f.rule == 'TEST_DISABLED' and f.shape == 'param_cases_removed' for f in findings)


def test_preexisting_async_collection_is_not_assumed_to_be_a_known_ordinary_test():
    ir, _, _ = run(BEFORE.replace('def test_double', 'async def test_double'), AFTER, PROD)
    assert all(unit.before.param_cases is None for file in ir.files for unit in file.units if unit.before)
