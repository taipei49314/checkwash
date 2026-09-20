"""Native setup suppression must not hide behind an ordinary hook name."""
import os
import subprocess
import sys

import pytest

from test_issue84_runtime_hooks import judge

SOURCE = "import pytest\ndef pytest_runtest_setup(item):\n    pytest.skip('x')\n"
NOOP = "@pytest.fixture(autouse=True)\ndef _quiet():\n    yield\n"


def controls(source, before=None):
    return [finding for finding in judge(source, before) if finding.rule == 'TEST_DISABLED']


@pytest.mark.parametrize('source', [SOURCE,
    SOURCE.replace('pytest.skip', 'pytest.xfail'),
    SOURCE.replace('import pytest', 'import pytest as pt').replace('pytest.skip', 'pt.skip'),
    SOURCE.replace('import pytest', 'from pytest import skip as ignore').replace('pytest.skip', 'ignore'),
    SOURCE.replace("skip('x')", 'skip()'),
    SOURCE.replace('(item)', '()'),
    SOURCE.replace('def pytest_', '@pytest.hookimpl(tryfirst=True)\ndef pytest_'),
    SOURCE.replace('def pytest_', NOOP + 'import pytest\ndef pytest_'),
    SOURCE + NOOP,
])
def test_closed_setup_suppression_adds_high_existing_control(source):
    found = controls(source)
    assert len(found) == 1 and found[0].severity == 'high'
    assert 'execution/report suppression' in found[0].message


@pytest.mark.parametrize('source', [
    SOURCE.replace('pytest.skip', 'custom.skip'),
    SOURCE.replace('import pytest', 'import other as pytest'),
    SOURCE + '\npytest_runtest_setup = None\n',
    SOURCE + '\npytest = custom\n',
    SOURCE + '\npytest.skip = custom\n',
    SOURCE + '\ndef pytest_runtest_setup(item):\n    pass\n',
    SOURCE.replace('(item)', '(pytest)'),
    SOURCE.replace('import pytest', 'import pytest as item').replace('pytest.skip', 'item.skip'),
    SOURCE.replace('(item)', '(item=callback())'),
    SOURCE.replace('(item)', '(item: callback())'),
    SOURCE.replace('def pytest_', '@decorate\ndef pytest_'),
    SOURCE.replace('def pytest_', '@pytest.hookimpl(wrapper=True)\ndef pytest_'),
    SOURCE.replace('def pytest_', '@pytest.hookimpl(tryfirst=True, tryfirst=True)\ndef pytest_'),
    SOURCE.replace('def pytest_', 'async def pytest_'),
    SOURCE.replace("    pytest.skip('x')", "    if False:\n        pytest.skip('x')"),
    SOURCE.replace("    pytest.skip('x')", "    def unused():\n        pytest.skip('x')"),
    SOURCE.replace("    pytest.skip('x')", "    return\n    pytest.skip('x')"),
    SOURCE.replace("    pytest.skip('x')", "    raise RuntimeError()\n    pytest.skip('x')"),
    SOURCE.replace("    pytest.skip('x')", "    if True:\n        pass\n    else:\n        pytest.skip('x')"),
    SOURCE.replace("skip('x')", 'skip(callback())'),
    SOURCE.replace("skip('x')", 'skip(*args)'),
    SOURCE.replace("skip('x')", 'skip(reason=callback())'),
    SOURCE.replace('import pytest', 'import pytest\nmutate()'),
    SOURCE + NOOP.replace('    yield', '    pytest.skip("x")\n    yield'),
    SOURCE + NOOP.replace('def _quiet():', 'def _quiet(pytest):'),
    SOURCE + NOOP.replace('    yield', '    yield 1'),
])
def test_unproved_shadowed_or_unexecuted_hook_is_not_positive_evidence(source):
    assert not controls(source)


def test_existing_effect_is_not_repeated_for_format_only_change():
    assert not controls(SOURCE + '\n# comment\n', SOURCE)


def test_old_inert_hook_becoming_skip_is_detected():
    assert controls(SOURCE, SOURCE.replace("pytest.skip('x')", 'pass'))


@pytest.mark.parametrize('effect', ['skip', 'xfail'])
@pytest.mark.parametrize('sibling', ['', NOOP])
def test_real_setup_hook_skips_a_completed_failure(tmp_path, effect, sibling):
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_case.py').write_text('def test_case():\n    assert 1 == 2\n', encoding='utf-8')
    env = {**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests']
    before = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 1 and '1 failed' in before.stdout
    source = SOURCE.replace('pytest.skip', 'pytest.' + effect) + sibling
    (tests / 'conftest.py').write_text(source, encoding='utf-8')
    after = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0 and ('1 skipped' if effect == 'skip' else '1 xfailed') in after.stdout
    assert controls(source)[0].severity == 'high'
