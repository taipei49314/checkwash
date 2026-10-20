"""A conftest that swaps what pytest runs for a no-op is a runtime control (#432).

Three direct spellings are read (ruling 432.Q2): the item callback
(`item.runtest`, `item.obj`, `item._obj`) in a closed list of hooks, `runtest`
on pytest's item classes, and a native `unittest.TestCase` method. Each is a
generated matrix in the style of tests/test_neutralization_matrix.py: every
cell reports TEST_DISABLED at high, or is an honest control that stays
silent, or is a named residual pinned silent. Closing a residual later means
striking it from its list, a recorded act.
"""
import datetime
import os
import subprocess
import sys
import unittest

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import conftest_controls as cc
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.runtime_controls import TESTCASE_METHODS


def judge(source, before=None, path="tests/conftest.py"):
    change = FileChange(path, "added" if before is None else "modified",
                        before.encode() if before is not None else None, source.encode())
    # Synthetic changes: every other path is absent at the base.
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 14),
                   root_reader=lambda path: None)[1]


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


# The issue's two shapes.
ISSUE_A = "import pytest\n\n\n@pytest.hookimpl(tryfirst=True)\ndef pytest_runtest_call(item):\n    item.runtest = lambda: None\n"
ISSUE_B = "import unittest\n\nunittest.TestCase.assertEqual = lambda self, *args, **kwargs: None\n"
CLASS_LEVEL = "import pytest\n\npytest.Function.runtest = lambda self: None\n"
CALL_TEST_METHOD = "import unittest\n\nunittest.TestCase._callTestMethod = lambda self, method: None\n"
CAPTURE_AND_CALL = "def pytest_runtest_call(item):\n    original = item.runtest\n    item.runtest = lambda: original()\n"
FORWARDING = ("import unittest\n\n_original = unittest.TestCase.assertEqual\n\n\n"
              "def _assert_equal(self, first, second, msg=None):\n    return _original(self, first, second, msg)\n\n\n"
              "unittest.TestCase.assertEqual = _assert_equal\n")


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
    body = "".join("    " + line.format(r=receiver) + "\n" for line in form[1])
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
    pytest.param(call_hook("while True:", "    " + WRITE, "    break"), id="while-loop"),
    pytest.param(HEAD + "def pytest_fixture_setup(fixturedef, request):\n    request.node.runtest = lambda: None\n",
                 id="fixture-setup-request-node"),
    pytest.param(HEAD + "def pytest_pycollect_makeitem(collector, name, obj):\n    if name.startswith('test_'):\n"
                 "        item = pytest.Function.from_parent(collector, name=name)\n        " + WRITE + "\n"
                 "        return [item]\n", id="pycollect-makeitem"),
    # Carriers are traced generously, toward silence: a receiver called with
    # the item, and a name traced anywhere in the file, both count.
    pytest.param(call_hook("log.debug(item)", "item.runtest = lambda: log.debug('skipped')"), id="call-tainted-receiver"),
    pytest.param(HEAD + "def _describe():\n    log.debug(pytest.Function)\n\n\n"
                 "def pytest_runtest_call(item):\n    item.runtest = lambda: log.debug('skipped')\n", id="file-wide-taint"),
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
    for source in (ISSUE_A, ISSUE_B, CLASS_LEVEL):
        for before in (None, "import pytest\n"):
            hits = [f for f in judge(source, before, path) if f.rule == "TEST_DISABLED"]
            assert hits and all(f.severity == "high" for f in hits), (source, before)


def test_a_test_module_does_not_carry_these_suite_controls():
    for source in (ISSUE_A, ISSUE_B, CLASS_LEVEL):
        assert markers(source, conftest=False) == []


# --- Native unittest.TestCase methods ----------------------------------------

# (id, prefix, indent): every place a TestCase write is read.
TESTCASE_SCOPES = [
    ("module", "import unittest\n\n", ""),
    ("module-beside-fixture", "import os\nimport unittest\n\nimport pytest\n\n\n" + FIXTURE, ""),
    ("version-gated", "import sys\nimport unittest\n\nif sys.version_info >= (3, 11):\n", "    "),
    ("configure-hook", "import unittest\n\n\ndef pytest_configure(config):\n", "    "),
    ("local-import-hook", "def pytest_sessionstart(session):\n    import unittest\n", "    "),
]

TESTCASE_FORMS = [
    ("assertEqual", ["unittest.TestCase.assertEqual = lambda self, *args, **kwargs: None"]),
    ("assertTrue", ["unittest.TestCase.assertTrue = lambda self, expr, msg=None: None"]),
    ("case-module", ["unittest.case.TestCase.assertEqual = lambda self, first, second, msg=None: None"]),
    ("from-import", ["from unittest import TestCase as Case", "Case.assertEqual = lambda *args, **kwargs: None"]),
    ("setattr", ["setattr(unittest.TestCase, 'assertEqual', lambda *args, **kwargs: None)"]),
    ("alias", ["Case = unittest.TestCase", "Case.assertEqual = lambda *args, **kwargs: None"]),
    ("same-file-def", ["def _accept(self, *args, **kwargs):", "    pass", "unittest.TestCase.assertEqual = _accept"]),
    ("callTestMethod", ["unittest.TestCase._callTestMethod = lambda self, method: None"]),
    ("fail", ["unittest.TestCase.fail = lambda self, msg=None: None"]),
]


def case_source(scope, form):
    _id, prefix, indent = scope
    return prefix + "".join(indent + line + "\n" for line in form[1])


TESTCASE_CELLS = [pytest.param(scope, form, id=f"{scope[0]}-{form[0]}")
                  for scope in TESTCASE_SCOPES for form in TESTCASE_FORMS]


@pytest.mark.parametrize("scope,form", TESTCASE_CELLS)
def test_testcase_method_cell_reports(scope, form):
    assert_reports(case_source(scope, form))


def test_every_listed_testcase_method_reports():
    for method in sorted(TESTCASE_METHODS):
        source = f"import unittest\n\nunittest.TestCase.{method} = lambda *args, **kwargs: None\n"
        assert effects(source) == [f"testcase-{method}-replaced"], method


def test_the_method_list_covers_this_python():
    """Every native assertion method of the running Python is listed; a checker factory and class attributes are not."""
    native = {name for name in dir(unittest.TestCase)
              if name.startswith(("assert", "fail")) and name != "failureException"}
    if sys.version_info < (3, 14):
        # The list covers Python 3.11-3.13 (ruling 432.Q2); 3.14's new methods are a follow-up.
        assert native <= TESTCASE_METHODS, sorted(native - TESTCASE_METHODS)
    assert not {"_getAssertEqualityFunc", "addTypeEqualityFunc", "failureException", "maxDiff",
                "longMessage"} & TESTCASE_METHODS


TC = "import unittest\n\n"
NOOP = "lambda *args, **kwargs: None"

TESTCASE_HONEST = [
    pytest.param(FORWARDING, id="forwarding-wrapper"),
    pytest.param(TC + "unittest.TestCase.assertItemsEqual = unittest.TestCase.assertCountEqual\n", id="compat-alias"),
    pytest.param(TC + "unittest.TestCase.maxDiff = None\n", id="maxDiff"),
    pytest.param(TC + "unittest.TestCase.longMessage = True\n", id="longMessage"),
    pytest.param(TC + "def _assert_true(self, expr, msg=None):\n    if not expr:\n        raise self.failureException(msg)\n\n\n"
                 "unittest.TestCase.assertTrue = _assert_true\n", id="raising-reimplementation"),
    pytest.param(TC + "unittest.TestCase.assertBetween = lambda self, value, low, high: None\n", id="new-helper"),
    pytest.param(TC + "if not hasattr(unittest.TestCase, 'assertNoLogs'):\n"
                 "    unittest.TestCase.assertNoLogs = lambda self, *args, **kwargs: self.assertLogs(*args, **kwargs)\n",
                 id="version-shim"),
    pytest.param(TC + "_original = unittest.TestCase.assertEqual\nunittest.TestCase.assertEqual = " + NOOP
                 + "\nunittest.TestCase.assertEqual = _original\n", id="restored"),
    pytest.param(TC + "if False:\n    unittest.TestCase.assertEqual = " + NOOP + "\n", id="dead-branch"),
]


@pytest.mark.parametrize("source", TESTCASE_HONEST)
def test_honest_testcase_writes_stay_silent(source):
    assert_silent(source)


TESTCASE_RESIDUALS = [
    pytest.param(TC + "unittest.TestCase.assertEqual = unittest.TestCase.assertTrue\n", id="weaker-alias"),
    pytest.param(TC + "unittest.TestCase.assertEqual = lambda *args, **kwargs: print('skipped')\n", id="body-calls"),
    pytest.param(TC + "unittest.TestCase._getAssertEqualityFunc = lambda self, first, second: (" + NOOP + ")\n",
                 id="equality-func-factory"),
    pytest.param(TC + "unittest.TestCase.failureException = type('Never', (Exception,), {})\n", id="failureException"),
    pytest.param(TC + "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _quiet(monkeypatch):\n"
                 "    monkeypatch.setattr(unittest.TestCase, 'assertEqual', " + NOOP + ")\n", id="monkeypatch-fixture"),
    pytest.param(TC + "for name in ('assertEqual', 'assertTrue'):\n    setattr(unittest.TestCase, name, " + NOOP + ")\n",
                 id="loop"),
    pytest.param(TC + "setattr(unittest.TestCase, 'assert' + 'Equal', " + NOOP + ")\n", id="computed-name"),
    pytest.param(TC + "class QuietCase(unittest.TestCase):\n    def assertEqual(self, *args, **kwargs):\n        pass\n",
                 id="subclass-in-conftest"),
    pytest.param("from django.test import TestCase\n\nTestCase.assertEqual = " + NOOP + "\n", id="imported-subclass"),
    pytest.param(TC + "try:\n    import xmlrunner\nexcept ImportError:\n    unittest.TestCase.assertEqual = " + NOOP + "\n",
                 id="except-handler"),
    pytest.param("import functools\n" + TC + "unittest.TestCase.assertEqual = functools.partial(" + NOOP + ")\n",
                 id="call-built-partial"),
    pytest.param("import functools\n" + TC + "@functools.wraps(unittest.TestCase.assertEqual)\n"
                 "def _accept(self, *args, **kwargs):\n    pass\n\n\nunittest.TestCase.assertEqual = _accept\n", id="decorated-def"),
    pytest.param(TC + "_init = unittest.TestCase.__init__\n\n\ndef _quiet_init(self, *args, **kwargs):\n"
                 "    _init(self, *args, **kwargs)\n    self.addTypeEqualityFunc(int, " + NOOP + ")\n\n\n"
                 "unittest.TestCase.__init__ = _quiet_init\n", id="type-equality-func"),
    pytest.param("import sys\n" + TC + "sys.modules['unittest'].TestCase.assertEqual = " + NOOP + "\n",
                 id="sys-modules-lookup"),
    # Seven unknown top-level conditions exceed the reader's 64 path states,
    # and module scope is then not read at all.
    pytest.param(TC + "".join(f"if FLAG_{i}:\n    pass\n" for i in range(7))
                 + "unittest.TestCase.assertEqual = " + NOOP + "\n", id="path-state-cap"),
]


@pytest.mark.parametrize("source", TESTCASE_RESIDUALS)
def test_testcase_residual_is_pinned_silent(source):
    assert_silent(source)


def test_each_testcase_method_is_its_own_effect():
    source = (TC + "_original = unittest.TestCase.assertTrue\nunittest.TestCase.assertEqual = " + NOOP + "\n"
              "unittest.TestCase.assertTrue = lambda self, expr, msg=None: _original(self, expr, msg)\n")
    assert effects(source) == ["testcase-assertEqual-replaced"]


def test_module_scope_is_the_module_pseudo_hook():
    """Never `fixture`, which conftest_controls classifies as FIXTURE_SETUP."""
    for source, effect in ((ISSUE_B, "testcase-assertEqual-replaced"), (CLASS_LEVEL, "Function-runtest-replaced")):
        names = [m.name for m in markers(source)]
        assert len(names) == 1 and names[0].startswith(f"conftest.runtime.module.{effect}."), names


# --- runtest on pytest's item classes ----------------------------------------

# (id, import line, class expression)
ITEM_CLASSES = [
    ("pytest-Function", "import pytest\n", "pytest.Function"),
    ("pytest-Item", "import pytest\n", "pytest.Item"),
    ("python-Function", "import _pytest.python\n", "_pytest.python.Function"),
    ("unittest-TestCaseFunction", "import _pytest.unittest\n", "_pytest.unittest.TestCaseFunction"),
    ("from-python-Function", "from _pytest.python import Function\n", "Function"),
    ("from-pytest-alias", "from pytest import Function as PyFunction\n", "PyFunction"),
]
CLASS_SCOPES = [("module", "\n", ""), ("configure-hook", "\n\ndef pytest_configure(config):\n", "    ")]
CLASS_FORMS = [
    ("lambda", ["{c}.runtest = lambda self: None"]),
    ("setattr", ["setattr({c}, 'runtest', lambda self: None)"]),
    ("same-file-def", ["def _runtest(self):", "    pass", "{c}.runtest = _runtest"]),
]
CLASS_CELLS = [pytest.param(cls, scope, form, id=f"{cls[0]}-{scope[0]}-{form[0]}")
               for cls in ITEM_CLASSES for scope in CLASS_SCOPES for form in CLASS_FORMS]


@pytest.mark.parametrize("cls,scope,form", CLASS_CELLS)
def test_item_class_runtest_cell_reports(cls, scope, form):
    _id, imports, expression = cls
    source = imports + scope[1] + "".join(scope[2] + line.format(c=expression) + "\n" for line in form[1])
    assert_reports(source)


@pytest.mark.parametrize("source", [
    pytest.param("import _pytest.unittest\n\n\ndef runtest(self):\n    self._testcase(result=self)\n\n\n"
                 "_pytest.unittest.TestCaseFunction.runtest = runtest\n", id="django-style-runtest"),
    pytest.param("import pytest\n\n_original = pytest.Function.runtest\npytest.Function.runtest = lambda self: _original(self)\n",
                 id="capture-and-call"),
    pytest.param("import time\n\nimport pytest\n\n_original = pytest.Function.runtest\n\n\ndef _timed(self):\n"
                 "    start = time.monotonic()\n    try:\n        return _original(self)\n    finally:\n"
                 "        print(time.monotonic() - start)\n\n\npytest.Function.runtest = _timed\n", id="timing-wrapper"),
])
def test_delegating_item_class_runtest_stays_silent(source):
    assert_silent(source)


@pytest.mark.parametrize("source", [
    pytest.param("import pytest\n\npytest.Function.runtest = pytest.Function.setup\n", id="other-object-attribute"),
    pytest.param("import pytest\n\nfor cls in (pytest.Function, pytest.Item):\n    cls.runtest = lambda self: None\n",
                 id="loop"),
    pytest.param("import pytest\n\npytest.Function.runtest = lambda self: print(self)\n", id="mentions-self"),
    pytest.param(call_hook("type(item).runtest = lambda self: None"), id="type-of-item"),
    pytest.param(call_hook("item.__class__.runtest = lambda self: None"), id="dunder-class"),
    pytest.param("import pytest\n\n\nclass QuietFunction(pytest.Function):\n    def runtest(self):\n        pass\n",
                 id="subclass-in-conftest"),
    pytest.param("import _pytest.nodes\n\n_pytest.nodes.Item.runtest = lambda self: None\n", id="unlisted-class-spelling"),
])
def test_item_class_residual_is_pinned_silent(source):
    assert_silent(source)


# --- Real pytest ---------------------------------------------------------------

PYTEST_TEST = "def test_value():\n    assert 0 == 1\n"
UNITTEST_TEST = ("import unittest\n\n\nclass TestValue(unittest.TestCase):\n"
                 "    def test_value(self):\n        self.assertEqual(0, 1)\n")


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
    pytest.param(PYTEST_TEST, CLASS_LEVEL, id="class-level-runtest"),
    pytest.param(UNITTEST_TEST, ISSUE_B, id="testcase-assertEqual"),
    pytest.param(UNITTEST_TEST, CALL_TEST_METHOD, id="testcase-callTestMethod"),
])
def test_real_pytest_failing_test_turns_green_and_detector_blocks(tmp_path, test_source, conftest):
    after = run_pytest(tmp_path, test_source, conftest)
    assert after.returncode == 0, after.stdout + after.stderr
    assert_reports(conftest)


@pytest.mark.parametrize("test_source,conftest", [
    pytest.param(PYTEST_TEST, CAPTURE_AND_CALL, id="item-capture-and-call"),
    pytest.param(UNITTEST_TEST, FORWARDING, id="testcase-forwarding"),
])
def test_real_pytest_delegating_replacement_still_fails_and_detector_is_silent(tmp_path, test_source, conftest):
    after = run_pytest(tmp_path, test_source, conftest)
    assert after.returncode == 1, after.stdout + after.stderr
    assert_silent(conftest)


# Ruling R38 on #432 (2026-10-19): one more reporting cell runs under real
# pytest, the one the 2026-10-14 sweep plan named as one that must report.
# It is the source test_each_attribute_is_its_own_effect judges.
EMPTY_OBJ_DELEGATING_RUNTEST = call_hook("item.obj = lambda *args, **kwargs: None", "original = item.runtest",
                                         "item.runtest = lambda: original()")


def test_real_pytest_empty_obj_behind_a_delegating_runtest_turns_green_and_detector_blocks(tmp_path):
    """Function.runtest calls item.obj through pytest_pyfunc_call, so the delegating runtest runs the empty obj."""
    after = run_pytest(tmp_path, PYTEST_TEST, EMPTY_OBJ_DELEGATING_RUNTEST)
    assert after.returncode == 0, after.stdout + after.stderr
    assert effects(EMPTY_OBJ_DELEGATING_RUNTEST) == ["item-obj-replaced"]
    assert_reports(EMPTY_OBJ_DELEGATING_RUNTEST)
