"""A conftest that forces pytest's exit status is a runtime control (#422)."""
import datetime
import os
import subprocess
import sys

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import conftest_controls as cc
from checkwash.frontends.python.frontend import parse_python


def judge(source, before=None, path="tests/conftest.py"):
    change = FileChange(path, "added" if before is None else "modified",
                        before.encode() if before is not None else None, source.encode())
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 14))[1]


def markers(source):
    parsed = parse_python(source.encode(), collect_tests=True, conftest=True)
    return [m for unit in parsed.units for m in unit.side.markers if m.name.startswith("conftest.runtime.exit.")]


SESSIONFINISH = "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n"
PYTEST_EXIT = "import pytest\n\n\ndef pytest_sessionfinish(session, exitstatus):\n    pytest.exit('done', returncode=0)\n"
UNCONFIGURE = "import os\n\n\ndef pytest_unconfigure(config):\n    os._exit(0)\n"
MODULE = "import os\n\nos._exit(0)\n"
RESET = ("import pytest\n\n\n@pytest.hookimpl(wrapper=True)\ndef pytest_runtestloop(session):\n"
         "    result = yield\n    session.testsfailed = 0\n    return result\n")
RECIPE = "def pytest_sessionfinish(session, exitstatus):\n    if exitstatus == 5:\n        session.exitstatus = 0\n"
FINISH = "def pytest_sessionfinish(session, exitstatus):\n"

FORCING = [
    pytest.param(SESSIONFINISH, id="issue-example"),
    pytest.param("import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n" + FINISH
                 + "    yield\n    session.exitstatus = 0\n", id="hookwrapper"),
    pytest.param("import pytest\n\n\n@pytest.hookimpl(wrapper=True)\n" + FINISH
                 + "    yield\n    session.exitstatus = 0\n", id="wrapper"),
    pytest.param(PYTEST_EXIT, id="pytest-exit"),
    pytest.param("import os\n\n\n" + FINISH + "    os._exit(0)\n", id="os-exit-sessionfinish"),
    pytest.param(UNCONFIGURE, id="os-exit-unconfigure"),
    pytest.param(MODULE, id="os-exit-module-scope"),
    pytest.param("import sys\n\n\ndef pytest_unconfigure(config):\n    sys.exit(0)\n", id="sys-exit-unconfigure"),
    pytest.param("def pytest_keyboard_interrupt(excinfo):\n    raise SystemExit\n", id="systemexit-keyboard-interrupt"),
    pytest.param("import sys\n\n\ndef pytest_internalerror(excrepr, excinfo):\n    sys.exit(0)\n",
                 id="sys-exit-internalerror"),
    pytest.param("def pytest_terminal_summary(terminalreporter, exitstatus, config):\n"
                 "    terminalreporter._session.exitstatus = 0\n", id="terminal-summary-write"),
    pytest.param("class Plugin:\n    def pytest_sessionfinish(self, session, exitstatus):\n"
                 "        session.exitstatus = 0\n\n\ndef pytest_configure(config):\n"
                 "    config.pluginmanager.register(Plugin())\n", id="plugin-method"),
    pytest.param(RESET, id="testsfailed-reset"),
    pytest.param(FINISH + "    session.testsfailed -= 1\n", id="testsfailed-decrement"),
    pytest.param("import pytest\n\n\n" + FINISH + "    pytest.exit('no tests', returncode=5)\n", id="returncode-5"),
    pytest.param("import os\n\n\ndef _bye():\n    os._exit(0)\n\n\ndef pytest_unconfigure(config):\n    _bye()\n",
                 id="same-file-helper"),
    pytest.param("import os\n\nimport pytest\n\n\n@pytest.fixture(scope='session', autouse=True)\n"
                 "def stop_after_tests():\n    yield\n    os._exit(0)\n", id="session-fixture-teardown"),
    pytest.param("import atexit\nimport os\n\natexit.register(os._exit, 0)\n", id="atexit-os-exit"),
    pytest.param(FINISH + "    session.exitstatus = 256\n", id="status-256"),
    pytest.param("class _Z:\n    exitstatus = 0\n\n\n" + FINISH + "    session.exitstatus = _Z.exitstatus\n",
                 id="other-receiver-status"),
    pytest.param("_saved = []\n\n\n" + FINISH + "    if exitstatus == 5:\n        session.exitstatus = 0\n"
                 "    _saved.append(session)\n\n\ndef pytest_unconfigure(config):\n    if _saved:\n"
                 "        pytest_sessionfinish(_saved[0], 5)\n", id="forged-hook-call"),
    pytest.param(FINISH + "    if exitstatus == 5:\n        pass\n    else:\n        session.exitstatus = 0\n",
                 id="recipe-else-branch"),
    pytest.param(FINISH + "    if exitstatus in (1, 5):\n        session.exitstatus = 0\n", id="recipe-wider-membership"),
    pytest.param(FINISH + "    if exitstatus != 0:\n        session.exitstatus = 0\n", id="nonzero-swallowed"),
    pytest.param("import os\n\nimport pytest\n\n\n@pytest.fixture\ndef guard(request):\n    def fin():\n"
                 "        os._exit(0)\n    request.addfinalizer(fin)\n", id="nested-finalizer"),
    pytest.param("import sys\n\n__name__ = '__main__'\nif __name__ == '__main__':\n    sys.exit(0)\n",
                 id="name-main-rebound"),
    pytest.param("from _pytest.outcomes import Exit\n\n\n" + FINISH + "    raise Exit('done', returncode=0)\n",
                 id="raise-exit"),
    pytest.param(FINISH + "    setattr(session, 'exitstatus', 0)\n", id="setattr"),
    pytest.param(FINISH + "    vars(session)['exitstatus'] = 0\n", id="vars-key"),
    pytest.param("ZERO = 0\n\n\n" + FINISH + "    session.exitstatus = ZERO\n", id="named-constant"),
    pytest.param(FINISH + "    session.exitstatus *= 0\n", id="augmented-assignment"),
    pytest.param("import os\n\n\ndef pytest_unconfigure(config):\n    pid = os.fork()\n    if pid == 0:\n"
                 "        pass\n    else:\n        os._exit(0)\n", id="fork-parent"),
    pytest.param("def pytest_unconfigure(config):\n    quit()\n", id="quit"),
    pytest.param("from sys import exit as leave\n\n\ndef pytest_unconfigure(config):\n    leave(0)\n",
                 id="sys-exit-alias"),
    pytest.param("import atexit\nimport os\n\n\ndef pytest_configure(config):\n    @atexit.register\n"
                 "    def bye():\n        os._exit(0)\n", id="decorated-atexit-nested"),
    pytest.param("import os\n\nimport pytest\n\n\n@pytest.fixture\ndef guard(request):\n    @request.addfinalizer\n"
                 "    def fin():\n        os._exit(0)\n", id="decorated-addfinalizer"),
    pytest.param("import sys\n\nglobals()['__name__'] = '__main__'\nif __name__ == '__main__':\n    sys.exit(0)\n",
                 id="name-main-computed"),
    pytest.param("import os\n\n\nclass _Bye:\n    def __init__(self):\n        os._exit(0)\n\n\n"
                 "def pytest_unconfigure(config):\n    _Bye()\n", id="class-constructor-helper"),
    pytest.param("import os\n\n\nclass Helper:\n    @staticmethod\n    def bye():\n        os._exit(0)\n\n\n"
                 "def pytest_unconfigure(config):\n    Helper.bye()\n", id="class-method-helper"),
    pytest.param(FINISH + "    session.__dict__.update(exitstatus=0)\n", id="dict-update"),
    pytest.param("import functools\nimport sys\n\nimport pytest\n\n\n@pytest.fixture(scope='session', autouse=True)\n"
                 "def stop(request):\n    request.addfinalizer(functools.partial(sys.exit, 0))\n",
                 id="sys-exit-passed-to-finalizer"),
]

HONEST = [
    pytest.param(RECIPE, id="recipe"),
    pytest.param("import pytest\n\n\n" + FINISH + "    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:\n"
                 "        session.exitstatus = pytest.ExitCode.OK\n", id="recipe-exitcode"),
    pytest.param("from _pytest.main import ExitCode\n\n\n" + FINISH
                 + "    if session.exitstatus is ExitCode.NO_TESTS_COLLECTED:\n        session.exitstatus = ExitCode.OK\n",
                 id="recipe-session-is"),
    pytest.param(FINISH + "    if exitstatus in (5,):\n        session.exitstatus = 0\n", id="recipe-in-tuple"),
    pytest.param(FINISH + "    match exitstatus:\n        case 5:\n            session.exitstatus = 0\n", id="recipe-match"),
    pytest.param(FINISH + "    session.exitstatus = 0 if exitstatus == 5 else exitstatus\n",
                 id="recipe-conditional-expression"),
    pytest.param("import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n" + FINISH
                 + "    yield\n    if session.exitstatus == 5:\n        session.exitstatus = 0\n", id="recipe-hookwrapper"),
    pytest.param("import json\n\n\n" + FINISH + "    with open('report.json', 'w', encoding='utf-8') as handle:\n"
                 "        json.dump({'exitstatus': int(exitstatus), 'failed': session.testsfailed}, handle)\n",
                 id="report-only"),
    pytest.param("import os\n\n\n" + FINISH + "    os._exit(exitstatus)\n", id="hang-workaround"),
    pytest.param("import os\n\n\n" + FINISH + "    os._exit(int(exitstatus))\n", id="hang-workaround-int"),
    pytest.param("import os\n\n\n" + FINISH + "    if exitstatus == 0:\n        os._exit(0)\n", id="zero-on-success"),
    pytest.param(FINISH + "    session.testsfailed += 1\n", id="testsfailed-increment"),
    pytest.param(FINISH + "    session.exitstatus = 1\n", id="nonzero-write"),
    pytest.param("import os\n\n\ndef pytest_unconfigure(config):\n    pid = os.fork()\n    if pid == 0:\n"
                 "        os._exit(0)\n    os.waitpid(pid, 0)\n", id="fork-child"),
    pytest.param("import os\n\n\ndef _child():\n    os._exit(0)\n", id="uncalled-helper"),
    pytest.param("import pytest\n\n\ndef pytest_configure(config):\n    pytest.exit('cannot run here')\n",
                 id="pytest-exit-without-returncode"),
    pytest.param("import sys\n\n\ndef pytest_configure(config):\n    if not config.getoption('verbose'):\n"
                 "        sys.exit('need -v')\n", id="sys-exit-message"),
    pytest.param("import sys\n\nif __name__ == '__main__':\n    sys.exit(0)\n", id="main-block"),
    pytest.param("import os\n\n\ndef pytest_unconfigure(config):\n    if False:\n        os._exit(0)\n",
                 id="false-literal-branch"),
    pytest.param("import os\n\n\ndef pytest_unconfigure(config):\n    def never():\n        os._exit(0)\n",
                 id="uncalled-nested-def"),
    pytest.param("import sys\n\n\ndef pytest_cmdline_main(config):\n    if config.option.version:\n"
                 "        sys.exit(0)\n", id="cmdline-main-residual"),
    pytest.param("def pytest_configure(config):\n    exit = config.getoption('exitfirst')\n    if exit:\n"
                 "        print('stopping at the first failure', exit)\n", id="local-variable-named-exit"),
    pytest.param("from pytest import exit\n\n\ndef pytest_configure(config):\n    exit(reason='cannot run here')\n",
                 id="pytest-exit-imported-as-exit"),
]

# An existing conftest the forcing spellings are added to (the issue's "new and existing conftest").
EXISTING = "import pytest\n"


@pytest.mark.parametrize("source", FORCING)
def test_forcing_spellings_block_at_high(source):
    assert markers(source)
    hits = [f for f in judge(source) if f.rule == "TEST_DISABLED"]
    assert hits and all(f.severity == "high" for f in hits)
    assert any("execution/report suppression" in f.message for f in hits)


@pytest.mark.parametrize("source", FORCING)
def test_forcing_spellings_block_when_added_to_an_existing_conftest(source):
    hits = [f for f in judge(source, EXISTING) if f.rule == "TEST_DISABLED"]
    assert hits and all(f.severity == "high" for f in hits)


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_issue_example_blocks_at_root_and_nested_conftest(path):
    hits = [f for f in judge(SESSIONFINISH, path=path) if f.rule == "TEST_DISABLED"]
    assert hits and all(f.severity == "high" for f in hits)


@pytest.mark.parametrize("source", HONEST)
def test_honest_and_unreached_spellings_stay_silent(source):
    assert markers(source) == []
    assert not [f for f in judge(source) if f.rule == "TEST_DISABLED"]


def test_markers_are_unguarded_runtime_controls():
    """Ruling 422.Q1: kind RUNTIME, never FIXTURE_SETUP, and no guard for COMPAT_GATE to read."""
    for param in FORCING:
        for marker in markers(param.values[0]):
            assert cc.marker_kind(marker.name) == cc.RUNTIME, marker.name
            assert not marker.name.startswith("conftest.runtime.fixture."), marker.name
            assert marker.guard is None, marker.name


def test_existing_recipe_widened_to_every_status_blocks():
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in judge(SESSIONFINISH, RECIPE))


def test_unchanged_override_is_not_reported_again():
    assert not [f for f in judge(SESSIONFINISH + "\n# explanation\n", SESSIONFINISH) if f.rule == "TEST_DISABLED"]


@pytest.mark.parametrize("source", [SESSIONFINISH, PYTEST_EXIT, UNCONFIGURE, MODULE, RESET])
def test_real_pytest_failing_suite_turns_green_and_detector_blocks(tmp_path, source):
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
