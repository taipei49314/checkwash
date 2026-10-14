"""A conftest that swaps what pytest runs for a no-op is a runtime control (#432).

The item callback (`item.runtest`, `item.obj`, `item._obj`) is read in a
closed list of hooks (ruling 432.Q2), as a generated matrix in the style of
tests/test_neutralization_matrix.py: every cell reports TEST_DISABLED at
high, or is an honest control that stays silent, or is a named residual
pinned silent. Closing a residual later means striking it from its list, a
recorded act.
"""
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


def markers(source, conftest=True):
    parsed = parse_python(source.encode(), collect_tests=True, conftest=conftest)
    return [m for unit in parsed.units for m in unit.side.markers if "-replaced." in m.name]


def effects(source):
    """The effect part of each marker name: `item-runtest-replaced`, ..."""
    return [m.name.split(".")[3] for m in markers(source)]


def assert_reports(source):
    found = markers(source)
    assert found, source
    for marker in found:
        # Ruling 432.Q5, Q6: RUNTIME, never FIXTURE_SETUP, and no guard for COMPAT_GATE to read.
        assert cc.marker_kind(marker.name) == cc.RUNTIME, marker.name
        assert not marker.name.startswith("conftest.runtime.fixture."), marker.name
        assert marker.guard is None, marker.name
    hits = [f for f in judge(source) if f.rule == "TEST_DISABLED"]
    assert hits and all(f.severity == "high" for f in hits), source
    assert any("execution/report suppression" in f.message for f in hits)


def assert_silent(source):
    assert markers(source) == [], source
    assert not [f for f in judge(source) if f.rule == "TEST_DISABLED"], source


# The issue's shape (a).
ISSUE_A = "import pytest\n\n\n@pytest.hookimpl(tryfirst=True)\ndef pytest_runtest_call(item):\n    item.runtest = lambda: None\n"
CAPTURE_AND_CALL = "def pytest_runtest_call(item):\n    original = item.runtest\n    item.runtest = lambda: original()\n"


# --- The item callback -------------------------------------------------------

HEAD = "import os\n\nimport pytest\n\n\n"
FIXTURE = "@pytest.fixture\ndef settings():\n    return os.environ\n\n\n"

# (id, prefix, decorator, signature, receiver, suffix): every hook whose callback write is read.
ITEM_HOOKS = [
    ("call-tryfirst", "", "@pytest.hookimpl(tryfirst=True)\n", "pytest_runtest_call(item)", "item", ""),
    ("call-undecorated", "", "", "pytest_runtest_call(item)", "item", ""),
    ("call-beside-fixture", FIXTURE, "", "pytest_runtest_call(item)", "item", ""),
    ("call-hookwrapper", "", "@pytest.hookimpl(hookwrapper=True)\n", "pytest_runtest_call(item)", "item", "    yield\n"),
    ("setup", "", "", "pytest_runtest_setup(item)", "item", ""),
    ("teardown", "", "", "pytest_runtest_teardown(item, nextitem)", "item", ""),
    ("protocol", "", "", "pytest_runtest_protocol(item, nextitem)", "item", ""),
    ("makereport", "", "", "pytest_runtest_makereport(item, call)", "item", ""),
    ("itemcollected", "", "", "pytest_itemcollected(item)", "item", ""),
    ("pyfunc", "", "", "pytest_pyfunc_call(pyfuncitem)", "pyfuncitem", ""),
]

# (id, body lines with `{r}` for the receiver): every write that reports.
ITEM_FORMS = [
    ("runtest", ["{r}.runtest = lambda: None"]),
    ("obj", ["{r}.obj = lambda *args, **kwargs: None"]),
    ("_obj", ["{r}._obj = lambda *args, **kwargs: None"]),
    ("setattr", ["setattr({r}, 'runtest', lambda: None)"]),
    ("alias", ["node = {r}", "node.runtest = lambda: None"]),
    ("skip-call", ["{r}.runtest = lambda: pytest.skip('flaky')"]),
    ("print-call", ["{r}.runtest = lambda: print('skipped')"]),
    ("local-def", ["def _noop(*args, **kwargs):", "    pass", "{r}.obj = _noop"]),
    ("conditional", ["if 'slow' in {r}.keywords:", "    {r}.runtest = lambda: None"]),
]


def item_source(hook, form):
    _id, prefix, decorator, signature, receiver, suffix = hook
    body = "".join("    " + line.format(r=receiver) + "\n" for line in form)
    return HEAD + prefix + decorator + "def " + signature + ":\n" + body + suffix


def call_hook(*lines):
    return HEAD + "def pytest_runtest_call(item):\n" + "".join("    " + line + "\n" for line in lines)


ITEM_CELLS = [pytest.param(hook, form, id=f"{hook[0]}-{form[0]}") for hook in ITEM_HOOKS for form in ITEM_FORMS]


@pytest.mark.parametrize("hook,form", ITEM_CELLS)
def test_item_callback_cell_reports(hook, form):
    assert_reports(item_source(hook, form))


@pytest.mark.parametrize("source", [
    pytest.param("def _noop(*args, **kwargs):\n    pass\n\n\ndef pytest_runtest_call(item):\n    item.runtest = _noop\n",
                 id="module-def"),
    pytest.param("_NOOP = lambda: None\n\n\ndef pytest_runtest_call(item):\n    item.runtest = _NOOP\n", id="module-lambda"),
])
def test_a_module_level_replacement_reports(source):
    assert_reports(source)


# Delegation is traced through carriers of the original, not matched by
# spelling (ruling 432.Q4): all of these run the test.
ITEM_HONEST = [
    pytest.param(call_hook("original = item.runtest", "def wrapped():", "    with open(os.devnull):",
                           "        original()", "item.runtest = wrapped"), id="capture-and-call"),
    pytest.param(call_hook("runner = TimeoutRunner(item.runtest, 30)", "item.runtest = lambda: runner.run()"),
                 id="runner-built-from-original"),
    pytest.param(call_hook("item._original_runtest = item.runtest", "item.runtest = lambda: item._original_runtest()"),
                 id="original-stored-on-item"),
    pytest.param(call_hook("item.runtest = lambda run=item.runtest: run()"), id="default-parameter"),
    pytest.param(call_hook("async def _run(**kwargs):", "    await item.obj(**kwargs)",
                           "item.obj = lambda **kwargs: asyncio.run(_run(**kwargs))"), id="local-async-runner"),
    pytest.param(call_hook("item.runtest = lambda: subprocess.check_call([sys.executable, '-m', 'pytest', item.nodeid])"),
                 id="rerun-by-nodeid"),
    pytest.param(call_hook("with open(os.devnull):", "    original = item.runtest", "item.runtest = lambda: original()"),
                 id="capture-in-with-block"),
    pytest.param(call_hook("_SAVED[item.nodeid] = item.runtest", "item.runtest = lambda: _SAVED[item.nodeid]()"),
                 id="saved-in-container"),
    pytest.param(call_hook("_SAVED.append(item.runtest)", "item.runtest = lambda: _SAVED[-1]()"), id="saved-by-append"),
    pytest.param(HEAD + "def pytest_pyfunc_call(pyfuncitem):\n    pyfuncitem.obj = wrap_in_sync(pyfuncitem.obj)\n",
                 id="wrap-in-sync"),
    pytest.param(call_hook("original = item.runtest", "item.runtest = lambda: None", "item.runtest = original"),
                 id="restored"),
    pytest.param(call_hook("original = item.runtest", "item.runtest = lambda: None", "item.runtest = lambda: original()"),
                 id="later-delegating-write"),
    pytest.param(call_hook("item.runtest = lambda: None", "del item.runtest"), id="deleted"),
    pytest.param(call_hook("if False:", "    item.runtest = lambda: None"), id="dead-branch"),
    pytest.param(call_hook("def never():", "    item.runtest = lambda: None"), id="uncalled-nested-def"),
    pytest.param(call_hook("item.user_properties.append(('started', True))"), id="read-only"),
]


@pytest.mark.parametrize("source", ITEM_HONEST)
def test_delegating_or_unreached_callback_writes_stay_silent(source):
    assert_silent(source)


WRITE = "item.runtest = lambda: None"

# Named residuals (ruling 432.Q2, Q4): spellings this round does not read.
ITEM_RESIDUALS = [
    pytest.param(HEAD + "def pytest_collection_finish(session):\n    for item in session.items:\n        " + WRITE + "\n",
                 id="collection-finish-loop"),
    pytest.param(HEAD + "async def pytest_runtest_call(item):\n    " + WRITE + "\n", id="async-hook"),
    pytest.param(HEAD + "def _call(item):\n    " + WRITE + "\n\n\npytest_runtest_call = _call\n", id="hook-bound-by-assignment"),
    pytest.param(HEAD + "@pytest.fixture(autouse=True)\ndef _quiet(request):\n    request.node.runtest = lambda: None\n",
                 id="autouse-fixture"),
    pytest.param(HEAD + "class Plugin:\n    def pytest_runtest_call(self, item):\n        " + WRITE + "\n\n\n"
                 "def pytest_configure(config):\n    config.pluginmanager.register(Plugin())\n", id="class-plugin"),
    pytest.param(call_hook("with open(os.devnull):", "    " + WRITE), id="with-block"),
    pytest.param(call_hook("try:", "    import xdist", "except ImportError:", "    " + WRITE), id="except-handler"),
    pytest.param(HEAD + "def pytest_exception_interact(node, call, report):\n    node.runtest = lambda: None\n",
                 id="other-hook-parameter"),
    pytest.param(call_hook("item.runtest = functools.partial(print)"), id="call-built-partial"),
    pytest.param(call_hook("item.runtest = make_noop()"), id="call-built-factory"),
    pytest.param(call_hook("@functools.lru_cache", "def _noop():", "    pass", "item.runtest = _noop"), id="decorated-def"),
    pytest.param(call_hook("item.runtest = NOOPS.runtest"), id="other-object-attribute"),
    pytest.param(call_hook("item.runtest = lambda: print(item)"), id="mentions-item"),
    pytest.param(call_hook("item.runtest = lambda: pytest.skip(item.nodeid)"), id="skip-with-nodeid"),
    pytest.param(call_hook("item.__setattr__('runtest', lambda: None)"), id="dunder-setattr"),
    pytest.param(call_hook("setattr(item, 'run' + 'test', lambda: None)"), id="computed-name"),
    pytest.param(call_hook("item.__dict__['runtest'] = lambda: None"), id="dict-write"),
    pytest.param(call_hook("item.runtest, item.obj = (lambda: None), (lambda: None)"), id="tuple-target"),
    pytest.param(call_hook(WRITE, "noop = item.runtest", "item.runtest = noop"), id="unread-rewrite"),
]


@pytest.mark.parametrize("source", ITEM_RESIDUALS)
def test_item_callback_residual_is_pinned_silent(source):
    assert_silent(source)


def test_each_attribute_is_its_own_effect():
    """pytest's Function.runtest calls item.obj, so a delegating runtest must not clear a no-op obj."""
    source = call_hook("item.obj = lambda *args, **kwargs: None", "original = item.runtest",
                       "item.runtest = lambda: original()")
    assert effects(source) == ["item-obj-replaced"]
    assert_reports(source)


@pytest.mark.parametrize("signature", ["pytest_runtest_protocol(item, nextitem)", "pytest_runtest_teardown(item, nextitem)"])
def test_a_write_on_nextitem_reports_under_its_own_key(signature):
    source = HEAD + f"def {signature}:\n    if nextitem is not None:\n        nextitem.runtest = lambda: None\n"
    assert effects(source) == ["nextitem-runtest-replaced"]
    assert_reports(source)


def test_a_write_under_a_condition_is_reported_and_widening_it_is_a_new_control():
    """Ruling 432.Q5: the guard is hashed into the name, as #84's controls are."""
    guarded = call_hook("if 'slow' in item.keywords:", "    " + WRITE)
    unguarded = call_hook(WRITE)
    assert [m.guard for m in markers(guarded)] == [None]
    assert {m.name for m in markers(guarded)} != {m.name for m in markers(unguarded)}
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in judge(unguarded, guarded))


def test_an_unchanged_replacement_is_not_reported_again():
    source = call_hook(WRITE)
    assert not [f for f in judge(source + "\n# explanation\n", source) if f.rule == "TEST_DISABLED"]


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_issue_shapes_block_in_a_new_and_an_existing_conftest(path):
    for source in (ISSUE_A,):
        for before in (None, "import pytest\n"):
            hits = [f for f in judge(source, before, path) if f.rule == "TEST_DISABLED"]
            assert hits and all(f.severity == "high" for f in hits), (source, before)


def test_a_test_module_does_not_carry_these_suite_controls():
    for source in (ISSUE_A,):
        assert markers(source, conftest=False) == []


# --- Real pytest ---------------------------------------------------------------

PYTEST_TEST = "def test_value():\n    assert 0 == 1\n"


def run_pytest(tmp_path, test_source, conftest):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(test_source, encoding="utf-8")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    before = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 1, before.stdout + before.stderr
    (tests / "conftest.py").write_text(conftest, encoding="utf-8")
    return subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("test_source,conftest", [
    pytest.param(PYTEST_TEST, ISSUE_A, id="item-runtest"),
])
def test_real_pytest_failing_test_turns_green_and_detector_blocks(tmp_path, test_source, conftest):
    after = run_pytest(tmp_path, test_source, conftest)
    assert after.returncode == 0, after.stdout + after.stderr
    assert_reports(conftest)


@pytest.mark.parametrize("test_source,conftest", [
    pytest.param(PYTEST_TEST, CAPTURE_AND_CALL, id="item-capture-and-call"),
])
def test_real_pytest_delegating_replacement_still_fails_and_detector_is_silent(tmp_path, test_source, conftest):
    after = run_pytest(tmp_path, test_source, conftest)
    assert after.returncode == 1, after.stdout + after.stderr
    assert_silent(conftest)
