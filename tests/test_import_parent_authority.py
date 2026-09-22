"""A unique pure leaf does not establish its real Python parent package."""
import ast
import os
import subprocess
import sys

import pytest

from checkwash.frontends.python.oracle_purity import pure_imported_calls


SOURCE = b'from app.prod import value\n'
CALL = ast.parse('value("abc")', mode='eval').body
PRODUCTION = b'def value(text):\n    return text\n'


def proof(files, module='app.prod'):
    source = SOURCE.replace(b'app.prod', module.encode())
    return pure_imported_calls(source, [CALL], path='tests/test_case.py', read=files.get)


@pytest.mark.parametrize('shadow', [
    'app.py', 'app/__init__.py', 'tests/app.py', 'tests/app/__init__.py',
])
@pytest.mark.parametrize('initializer', [None, b''])
def test_competing_parent_cannot_lend_the_src_leafs_authority(shadow, initializer):
    files = {'src/app/prod.py': PRODUCTION, shadow: b''}
    if initializer is not None:
        files['src/app/__init__.py'] = initializer
    assert not proof(files)


@pytest.mark.parametrize('shadow', ['app/sub.py', 'app/sub/__init__.py', 'tests/app/sub/__init__.py'])
def test_nested_namespace_parent_cannot_be_redirected(shadow):
    assert not proof({'src/app/sub/prod.py': PRODUCTION, shadow: b''}, 'app.sub.prod')


@pytest.mark.parametrize('files,module', [
    ({'src/app/prod.py': PRODUCTION}, 'app.prod'),
    ({'src/app/__init__.py': b'', 'src/app/prod.py': PRODUCTION}, 'app.prod'),
    ({'src/app/sub/prod.py': PRODUCTION}, 'app.sub.prod'),
    ({'src/app/sub/__init__.py': b'', 'src/app/sub/prod.py': PRODUCTION}, 'app.sub.prod'),
    ({'src/app/__init__.py': b'', 'src/app/sub/prod.py': PRODUCTION,
      'app/sub/__init__.py': b'mutate()\n'}, 'app.sub.prod'),
    ({'app/prod.py': PRODUCTION, 'src/app/other.py': b''}, 'app.prod'),
])
def test_unambiguous_regular_and_native_namespace_packages_remain_supported(files, module):
    assert proof(files, module)


@pytest.mark.parametrize('files', [
    {'src/app/prod.py': PRODUCTION, 'src/app.py': b''},
    {'src/app/prod.py': PRODUCTION, 'app/prod.py': PRODUCTION},
    {'src/app/prod.py': PRODUCTION, 'src/app/prod/__init__.py': PRODUCTION},
])
def test_nonpackage_parent_and_duplicate_leaves_do_not_guess_resolution(files):
    assert not proof(files)


@pytest.mark.parametrize('initializer,expected', [
    (None, 'review_native_namespace'),
    (b'', 'review_src_regular_package'),
])
def test_real_import_resolves_supported_namespace_and_regular_source(tmp_path, initializer, expected):
    # The isolated process starts with only the exact task-owned roots. This
    # checks Python's resolver without depending on modules pytest imported.
    package = tmp_path / 'src/app'
    package.mkdir(parents=True)
    (package / 'prod.py').write_text(f'def value(text):\n    return "{expected}"\n')
    if initializer is not None:
        (package / '__init__.py').write_bytes(initializer)
    script = 'import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; from app.prod import value; print(value("abc"))'
    result = subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), str(tmp_path / 'src')],
                            capture_output=True, text=True, check=True, env=os.environ)
    assert result.stdout.strip() == expected


def test_real_regular_parent_can_redirect_the_unique_src_leaf(tmp_path):
    (tmp_path / 'src/app').mkdir(parents=True)
    (tmp_path / 'src/app/prod.py').write_bytes(PRODUCTION)
    (tmp_path / 'app').mkdir()
    initializer = b'''import sys
from types import ModuleType
module = ModuleType('app.prod')
module.value = lambda text: 'redirected'
sys.modules['app.prod'] = module
'''
    (tmp_path / 'app/__init__.py').write_bytes(initializer)
    script = 'import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; from app.prod import value; print(value("abc"))'
    result = subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), str(tmp_path / 'src')],
                            capture_output=True, text=True, check=True, env=os.environ)
    assert result.stdout.strip() == 'redirected'
    assert not proof({'src/app/prod.py': PRODUCTION, 'app/__init__.py': initializer})
