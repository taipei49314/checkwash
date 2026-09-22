"""Execution/report hook suppression, with honest plugin controls (#84)."""
import datetime
import os
import subprocess
import sys

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


def judge(source, before=None, path="tests/conftest.py"):
    change = FileChange(path, "added" if before is None else "modified",
                        before.encode() if before is not None else None, source.encode())
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 9, 21))[1]


REPORT = """import pytest
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == 'call' and report.failed:
        report.outcome = 'passed'
        report.longrepr = None
"""
CALL = """import pytest
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if 'test_billing' in pyfuncitem.nodeid:
        return True
"""
FORCE = """import pytest
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    outcome = yield
    outcome.force_result(None)
"""
WRAPPER = """import pytest
@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        yield
    except AssertionError:
        pass
"""


@pytest.mark.parametrize("source", [REPORT, CALL, FORCE, WRAPPER,
    REPORT.replace("hookwrapper=True", "wrapper=True").replace("outcome = yield\n    report = outcome.get_result()", "report = yield"),
    REPORT.replace("report.outcome = 'passed'", "setattr(report, 'outcome', 'passed')"),
    "def pytest_runtest_protocol(item, nextitem):\n    return True\n",
    "def pytest_runtest_logreport(report):\n    report.outcome = 'passed'\n",
])
@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_hook_effects_block_at_root_and_nested_conftest(source, path):
    hits = [f for f in judge(source, path=path) if f.rule == "TEST_DISABLED"]
    assert hits and all(f.severity == "high" for f in hits)
    assert any("execution/report suppression" in f.message for f in hits)


@pytest.mark.parametrize("source", [
    "def pytest_pyfunc_call(pyfuncitem):\n    return None\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    pyfuncitem.obj(**pyfuncitem.funcargs)\n    return True\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    fn = pyfuncitem\n    fn.obj()\n    return True\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    if False:\n        return True\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    def never():\n        return True\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    raise RuntimeError('fail')\n    return True\n",
    "def pytest_pyfunc_call(pyfuncitem):\n    return True\npytest_pyfunc_call = None\n",
    REPORT.replace("report.outcome = 'passed'", "report.user_properties.append(('note', 'failed'))"),
    REPORT.replace("report.outcome = 'passed'", "report.outcome = 'passed'\n        report.outcome = 'failed'"),
    REPORT.replace("report = outcome.get_result()", "report = object()"),
    FORCE.replace("outcome.force_result(None)", "outcome.get_result()"),
    WRAPPER.replace("        pass", "        raise"),
    "import pytest\n@pytest.hookimpl(wrapper=True)\ndef pytest_pyfunc_call(pyfuncitem):\n    yield\n    return True\n",
])
def test_honest_and_nonexecuting_hook_controls_stay_silent(source):
    assert not [f for f in judge(source) if f.rule == "TEST_DISABLED"]


def test_existing_reporter_changed_to_suppress_failure_is_not_hidden_by_hook_name():
    before = REPORT.replace("report.outcome = 'passed'", "report.user_properties.append(('note', 'failed'))")
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in judge(REPORT, before))


def test_unchanged_effect_reformat_does_not_repeat_a_finding():
    assert not [f for f in judge(REPORT + "\n# explanation\n", REPORT) if f.rule == "TEST_DISABLED"]


def test_widened_predicate_is_a_new_control():
    before = CALL.replace("'test_billing' in pyfuncitem.nodeid", "pyfuncitem.name == 'test_one'")
    assert any(f.rule == "TEST_DISABLED" for f in judge(CALL, before))


@pytest.mark.parametrize("source", [REPORT, CALL, FORCE, WRAPPER])
def test_real_pytest_failing_oracle_turns_green_and_detector_blocks(tmp_path, source):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_billing.py").write_text("def test_billing():\n    assert 1 == 2\n", encoding="utf-8")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    before = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 1, before.stdout + before.stderr
    (tests / "conftest.py").write_text(source, encoding="utf-8")
    after = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0, after.stdout + after.stderr
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in judge(source))
