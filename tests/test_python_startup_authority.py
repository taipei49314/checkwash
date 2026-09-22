"""Repository interpreter startup must not forge optional builtin authority."""
import os
import subprocess
import sys

import pytest

from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.gitio.snapshot import search_source_mapping
from test_issue_expectation_families import run


PATH = 'tests/test_case.py'
PRODUCTION = 'def is_success(code):\n    return code == 200\n'
BEFORE = '''from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    assert is_success(201) == False
'''
AFTER = BEFORE.replace('    assert is_success(201)', '    if len([]):\n        assert is_success(201)')
STARTUP = '''import builtins, sys
_original_len = builtins.len
def checked_len(value):
    if sys._getframe(1).f_code.co_name == "test_only_200" and type(value) is list:
        return 1
    return _original_len(value)
builtins.len = checked_len
'''


def authority(context, path=PATH):
    snapshot = {path: AFTER.encode(), **context}
    return inert_test_execution_context(path, snapshot.get,
        lambda needles: search_source_mapping(snapshot, needles))


@pytest.mark.parametrize('root', ['', 'src/', 'tests/', 'tests/nested/'])
@pytest.mark.parametrize('module', ['sitecustomize', 'usercustomize'])
@pytest.mark.parametrize('suffix', ['.py', '/__init__.py'])
def test_every_possible_startup_module_and_package_requires_inert_source(root, module, suffix):
    candidate = root + module + suffix
    assert not authority({candidate: STARTUP.encode()}, path='tests/nested/test_case.py')


@pytest.mark.parametrize('content', [b'', b'pass\n', b'"An inert module docstring."\n'])
def test_inert_competing_startup_sources_are_safe_under_either_import_order(content):
    assert authority({'sitecustomize.py': content, 'src/sitecustomize/__init__.py': content,
                      'tests/usercustomize.py': content})


@pytest.mark.parametrize('active,inert', [
    ('sitecustomize.py', 'src/sitecustomize.py'),
    ('src/sitecustomize.py', 'sitecustomize.py'),
    ('src/sitecustomize/__init__.py', 'src/sitecustomize.py'),
    ('src/usercustomize.py', 'usercustomize/__init__.py'),
])
def test_competing_inert_candidate_does_not_hide_executable_startup(active, inert):
    assert not authority({active: STARTUP.encode(), inert: b''})


def test_collectable_sibling_roots_also_keep_startup_authority_closed():
    assert not authority({'other_tests/test_value.py': b'def test_value():\n    assert True\n',
                          'other_tests/sitecustomize.py': STARTUP.encode()})


@pytest.mark.parametrize('module', ['sitecustomize', 'usercustomize'])
def test_shared_table_equivalence_cannot_ignore_repository_startup(module):
    before = 'from app.prod import is_success\ndef test_first():\n    assert is_success(200) == True\ndef test_second():\n    assert is_success(201) == False\n'
    after = before.replace('def test_second():\n', '')
    ir, _, _ = run(before, after, PRODUCTION, context={f'src/{module}.py': STARTUP.encode()})
    assert not any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_real_sitecustomize_can_make_the_empty_length_guard_execute(tmp_path):
    for relative, data in {'src/app/__init__.py': '', 'src/app/prod.py': PRODUCTION,
                           'src/sitecustomize.py': STARTUP}.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(data, encoding='utf-8')
    test_file = tmp_path / PATH
    test_file.parent.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(tmp_path/'src'), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    for source in (BEFORE, AFTER):
        test_file.write_text(source, encoding='utf-8')
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '1 passed' in result.stdout
    # The actual guarded assertion runs: making just that answer wrong fails.
    test_file.write_text(AFTER.replace('is_success(201) == False', 'is_success(201) == True'), encoding='utf-8')
    wrong = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert wrong.returncode == 1 and '1 failed' in wrong.stdout
    assert not authority({'src/sitecustomize.py': STARTUP.encode()})
