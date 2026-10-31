"""A Python arrival pays only where the repository's pytest configuration collects it (D-193).

THREATMODEL row 179: arrival liveness read the unit's own markers and none of
the repository's collection settings, so a test moved into a file that the
repository's own pytest configuration never runs still earned the move
credit. These sources are parsed by CheckWash and never executed.
"""
import datetime
import json
import os
import subprocess
import sys

import pytest

from checkwash.arrival_collection import arrival_collector
from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


def collector(files, listed=None):
    """The predicate over the head snapshot `files`; `listed=True` lists that snapshot."""
    def read(path):
        value = files.get(path)
        if isinstance(value, Exception):
            raise value
        return value
    inventory = None
    if listed is True:
        inventory = lambda: sorted(files)  # noqa: E731
    elif listed is not None:
        inventory = lambda: list(listed)  # noqa: E731
    return arrival_collector(read, inventory)


def ini(text):
    return {"pytest.ini": ("[pytest]\n" + text + "\n").encode()}


# pytest refuses a pyproject holding both of its tables.
BOTH_TABLES = b'[tool.pytest]\npython_files = ["check_*.py"]\n\n[tool.pytest.ini_options]\naddopts = "-ra"\n'


@pytest.mark.parametrize("path,qualname,expected", [
    ("test_x.py", "test_a", True),
    ("x_test.py", "test_a", True),
    ("check_x.py", "test_a", False),
    ("test_x.txt", "test_a", False),
    ("tests/unit/test_x.py", "TestCase.test_a", True),
    ("test_x.py", "helper", False),
    ("test_x.py", "testing_helper", True),  # python_functions is a prefix
    ("test_x.py", "test_a#2", True),
    # norecursedirs is a glob over a directory's own name, not a prefix.
    (".hidden/test_x.py", "test_a", False),
    ("build/test_x.py", "test_a", False),
    ("builder/test_x.py", "test_a", True),
    ("venv/test_x.py", "test_a", False),
    ("venvs/test_x.py", "test_a", True),
    ("pkg.egg/test_x.py", "test_a", False),
    # pytest never enters a directory it takes for a virtual environment.
    ("tests/env/test_x.py", "test_a", False),
    ("tests/conda/test_x.py", "test_a", False),
])
def test_defaults_are_pytests_own(path, qualname, expected):
    files = {"tests/env/pyvenv.cfg": b"home = /usr/bin\n", "tests/conda/conda-meta/history": b""}
    assert collector(files)(path, qualname) is expected


@pytest.mark.parametrize("settings,path,expected", [
    ("python_files = test_*.py", "x_test.py", False),
    ("python_files = test_*.py", "test_x.py", True),
    ("python_files = check_*.py", "check_x.py", True),
    ("python_files = check_*.py", "test_x.py", False),
    ("python_files = test", "testing.py", False),  # a glob, never a prefix
    ("python_files = tests/*/test_*.py", "tests/a/test_x.py", True),
    ("python_files = tests/*/test_*.py", "test_x.py", False),
    ("norecursedirs = legacy", "legacy/test_x.py", False),
    ("norecursedirs = legacy", "build/test_x.py", True),  # it replaces the defaults
    ("norecursedirs = */legacy", "tests/legacy/test_x.py", False),
])
def test_configured_file_patterns(settings, path, expected):
    assert collector(ini(settings))(path, "test_a") is expected


@pytest.mark.parametrize("settings,qualname,expected", [
    ("python_functions = check_*", "test_a", False),
    ("python_functions = check_*", "check_a", True),
    ("python_functions = test should", "should_a", True),
    # A method of a class with bases may be a TestCase, which pytest's
    # unittest plugin collects by its own prefix; without knowing, the
    # configured pattern decides, which can only withhold a credit.
    ("python_functions = check_*", "Checks.test_a", False),
])
def test_configured_function_patterns(settings, qualname, expected):
    assert collector(ini(settings))("test_x.py", qualname) is expected


TREE = {"tests/test_a.py": b"", "tests/unit/test_b.py": b"", "src/app.py": b"", "build/tests/test_c.py": b""}


@pytest.mark.parametrize("settings,path,expected", [
    ("testpaths = tests", "tests/test_x.py", True),
    ("testpaths = tests", "test_x.py", False),
    ("testpaths = tests", "other/test_x.py", False),
    ("testpaths = nothere", "test_x.py", True),  # no testpath exists: pytest searches from the root
    ("testpaths = tests/*", "tests/unit/test_x.py", True),
    ("testpaths = tests/*", "tests/test_x.py", True),  # glob yields the file itself
    ("testpaths = tests/*", "tests/.hidden/test_x.py", False),  # glob skips hidden names
    ("testpaths = tests/*", "test_x.py", False),
    ("testpaths = tests/**/unit", "tests/unit/test_x.py", True),
    # An initial path and the directories above it are entered whatever
    # norecursedirs says, and the directories below it are not.
    ("testpaths = build/tests", "build/tests/test_x.py", True),
    ("testpaths = build/tests", "build/tests/build/test_x.py", False),
    ("addopts = tests", "tests/test_x.py", True),
    ("addopts = tests", "test_x.py", False),
    ("addopts = tests\ntestpaths = src", "tests/test_x.py", True),  # targets ignore testpaths
    ("addopts = .\ntestpaths = tests", "other/test_x.py", True),
    ("addopts = -ra --cov src -n 4 tests", "src/test_x.py", False),  # --cov takes src
    ("addopts = -ra --cov src -n 4 tests", "tests/test_x.py", True),
    ("addopts = --splinter-webdriver chrome", "test_x.py", True),  # a value naming no path
    ("addopts = tests/checks.py", "tests/checks.py", True),  # a named file, whatever its name
])
def test_testpaths_and_addopts_targets(settings, path, expected):
    # The arrival is in the head inventory, as every arrival is.
    assert collector({**TREE, path: b"", **ini(settings)}, listed=True)(path, "test_a") is expected


def test_the_inventory_is_listed_only_for_a_decision_that_needs_it():
    # A working tree's listing walks it whole, so an arrival inside the
    # testpaths never asks for it, and it is listed at most once.
    calls = []

    def lister():
        calls.append(1)
        return ["pytest.ini", "tests/test_a.py"]

    collected = arrival_collector(ini("testpaths = tests").get, lister)
    assert collected("tests/test_x.py", "test_a") and not calls
    assert not collected("other/test_x.py", "test_a") and calls == [1]
    assert not collected("more/test_x.py", "test_a") and calls == [1]


def test_without_an_inventory_a_testpath_and_a_target_are_unknown():
    testpaths = collector(ini("testpaths = tests"))
    assert testpaths("tests/test_x.py", "test_a")
    assert not testpaths("test_x.py", "test_a") and not testpaths.excludes("test_x.py")
    targets = collector(ini("addopts = tests"))
    assert not targets("tests/test_x.py", "test_a") and not targets.excludes("test_x.py")


@pytest.mark.parametrize("files,path,expected", [
    (ini("python_files = test_*.py"), "app_test.py", True),
    (ini("python_files = test_*.py"), "test_app.py", False),
    (ini("testpaths = tests"), "test_x.py", False),  # no testpath exists: the root
    ({**ini("testpaths = tests"), "tests/test_a.py": b""}, "other/test_x.py", True),
    ({"conftest.py": b'collect_ignore = ["test_legacy.py"]\n'}, "test_legacy.py", True),
    # A keyword expression selects tests, so a file is still decided.
    (ini('python_files = test_*.py\naddopts = -k "not slow"'), "app_test.py", True),
    (ini('addopts = -k "not slow"'), "test_x.py", False),
    # Unknown excludes nothing.
    ({"conftest.py": b"def pytest_ignore_collect(collection_path):\n    return True\n"}, "test_x.py", False),
    ({**ini("python_files = test_*.py"), "conftest.py": b"collect_ignore = list(range(0))\n"}, "app_test.py", True),
    # Native TOML is read as pytest 9 reads it; both pytest tables at once stop pytest.
    ({"pyproject.toml": b'[tool.pytest]\npython_files = ["check_*.py"]\n'}, "test_x.py", True),
    ({"pyproject.toml": BOTH_TABLES}, "test_x.py", False),
    (ini("addopts = --co"), "test_x.py", False),
])
def test_a_file_is_excluded_only_where_pytest_certainly_leaves_it_out(files, path, expected):
    assert collector(files, listed=True).excludes(path) is expected


@pytest.mark.parametrize("addopts,path,qualname,expected", [
    ("--ignore=tests/legacy", "tests/legacy/test_x.py", "test_a", False),
    ("--ignore=tests/legacy", "tests/legacy_more/test_x.py", "test_a", True),  # a path, not a prefix
    ("--ignore tests/test_x.py", "tests/test_x.py", "test_a", False),
    ("--ignore-glob=*legacy*", "tests/test_legacy.py", "test_a", False),
    ("--ignore-glob=*legacy*", "tests/test_x.py", "test_a", True),
    ("--ignore-glob=tests/*", "tests/a/test_x.py", "test_a", False),
    ("--deselect tests/test_x.py::test_a", "tests/test_x.py", "test_a", False),
    ("--deselect tests/test_x.py::test_a", "tests/test_x.py", "test_ab", False),  # a node id prefix
    ("--deselect tests/test_x.py::test_a", "tests/test_x.py", "test_b", True),
    ("--deselect tests/test_x.py::test_a[1]", "tests/test_x.py", "test_a", False),  # one of its rows
    ("--deselect tests/test_x.py::TestC", "tests/test_x.py", "TestC.test_a", False),
    ("-p no:randomly -p no:cacheprovider", "tests/test_x.py", "test_a", True),
    ('-m "not slow"', "tests/test_x.py", "test_a", True),
])
def test_addopts_selection(addopts, path, qualname, expected):
    assert collector(ini("addopts = " + addopts))(path, qualname) is expected


@pytest.mark.parametrize("files", [
    ini('addopts = -k "not slow"'),  # a test it selects is unknown
    ini("addopts = -kslow"),
    ini("addopts = --co"),
    ini("addopts = -p no:python"),
    ini("addopts = -p no:unittest"),
    ini("addopts = --pyargs pkg"),
    ini("addopts = --rootdir=sub"),
    ini("addopts = /abs/tests"),
    ini("addopts = ../tests"),
    ini("addopts = --ignore=/abs/tests"),
    ini("norecursedirs = /abs"),
    ini("python_files = a_*.py\npython_files = b_*.py"),  # ambiguous
    {"pyproject.toml": BOTH_TABLES},
    {"pytest.ini": EngineError("unreadable")},
    {"pytest.ini": b"[pytest]\npython_files = \xff\n"},
], ids=["k", "k-joined", "collect-only", "no-python", "no-unittest", "pyargs", "rootdir", "absolute-target",
        "outside-target", "absolute-ignore", "absolute-norecursedirs", "ambiguous", "both-tables", "unreadable",
        "undecodable"])
def test_what_cannot_be_read_pays_nothing(files):
    assert collector(files, listed=True)("tests/test_x.py", "test_a") is False


@pytest.mark.parametrize("files,path,expected", [
    ({"pyproject.toml": b'[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n'}, "check_x.py", True),
    ({"pyproject.toml": b'[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n'}, "test_x.py", False),
    ({"tox.ini": b"[pytest]\npython_files = check_*.py\n"}, "test_x.py", False),
    ({"setup.cfg": b"[tool:pytest]\npython_files = check_*.py\n"}, "test_x.py", False),
    # pytest.ini comes first; a pyproject without a pytest table does not
    # shadow the setup.cfg that has one.
    ({"pytest.ini": b"[pytest]\n", "setup.cfg": b"[tool:pytest]\npython_files = check_*.py\n"}, "test_x.py", True),
    ({"pyproject.toml": b"[project]\nname = 'x'\n", "setup.cfg": b"[tool:pytest]\npython_files = check_*.py\n"},
     "test_x.py", False),
])
def test_the_root_config_pytest_discovers_governs(files, path, expected):
    assert collector(files)(path, "test_a") is expected


@pytest.mark.parametrize("conftest,path,expected", [
    (b'collect_ignore = ["test_x.py"]\n', "test_x.py", False),
    (b'collect_ignore = ["test_x.py"]\n', "test_y.py", True),
    (b'collect_ignore = ["legacy"]\n', "legacy/test_x.py", False),  # a directory prunes its subtree
    (b'collect_ignore = []\ncollect_ignore.append("test_a.py")\n', "test_a.py", False),
    (b'collect_ignore = []\ncollect_ignore.extend(["test_b.py"])\n', "test_b.py", False),
    (b'collect_ignore = []\ncollect_ignore += ["test_c.py"]\n', "test_c.py", False),
    (b'collect_ignore = ["setup.py"]\ncollect_ignore.insert(0, "test_e.py")\n', "test_e.py", False),
    (b'import sys\ncollect_ignore = []\nif sys.version_info < (3, 8):\n    collect_ignore.append("test_d.py")\n',
     "test_d.py", False),  # every literal entry counts, whatever branch adds it
    (b'collect_ignore_glob = ["*_py2.py"]\n', "test_x_py2.py", False),
    (b'collect_ignore_glob = ["*_py2.py"]\n', "test_x.py", True),
    (b'import logging\nimport pytest\n\nlog = logging.getLogger(__name__)\n\n\n@pytest.fixture\n'
     b'def env(monkeypatch):\n    monkeypatch.setattr("os.sep", "/")\n', "test_x.py", True),
    # Words about the lists, and lists of another scope, are not the module's.
    (b'"""Shared fixtures. We removed the old collect_ignore list in 2024."""\nimport pytest\n', "test_x.py", True),
    (b'class Config:\n    collect_ignore = ["test_x.py"]\n', "test_x.py", True),
    (b'def pick(items):\n    collect_ignore = [i for i in items]\n    return collect_ignore\n', "test_x.py", True),
    (b'collect_ignore = ["test_y.py"]\n\n\ndef pick(collect_ignore):\n    return collect_ignore\n', "test_y.py", False),
])
def test_root_conftest_ignores(conftest, path, expected):
    assert collector({"conftest.py": conftest})(path, "test_a") is expected


@pytest.mark.parametrize("files", [
    {**ini("addopts = tests"), "conftest.py": b'collect_ignore = ["tests"]\n'},
    {**ini("addopts = tests --ignore=tests"), "tests/test_a.py": b""},
    {**ini("testpaths = tests"), "conftest.py": b'collect_ignore = ["tests"]\n'},
])
def test_an_initial_path_and_the_directories_above_it_are_never_ignored(files):
    # pytest asks pytest_ignore_collect only below the run's initial paths
    # (`isinitpath`), so these lists ignore nothing the run names.
    assert collector({**files, "tests/test_moved.py": b""}, listed=True)("tests/test_moved.py", "test_a") is True


def test_a_nested_conftest_ignores_below_its_own_directory():
    files = {"tests/conftest.py": b'collect_ignore = ["old"]\n'}
    assert collector(files)("tests/old/test_x.py", "test_a") is False
    assert collector(files)("old/test_x.py", "test_a") is True


@pytest.mark.parametrize("conftest", [
    b"def pytest_collection_modifyitems(items):\n    items.clear()\n",
    b"def pytest_ignore_collect(collection_path):\n    return True\n",
    b'pytest_plugins = ["helpers"]\n',
    b"from helpers import *\n",
    b"from helpers import collect_ignore\n",
    b"import glob\ncollect_ignore = glob.glob('test_*.py')\n",
    b'collect_ignore = ["setup.py"]\ncollect_ignore.remove("setup.py")\n',
    b"collect_ignore = []\ncollect_ignore[:] = ['test_x.py']\n",
    b"for collect_ignore in [[]]:\n    pass\n",
    b'import sys\nsys.modules[__name__].collect_ignore = ["test_x.py"]\n',
    b'import sys\ngetattr(sys.modules[__name__], "collect_ignore").append("test_x.py")\n',
    b'globals()["collect_ignore"] = ["test_x.py"]\n',
    b'collect_ignore = ["/abs/test_x.py"]\n',
    b"def broken(:\n",
    EngineError("unreadable"),
    b'collect_ignore = []\n\n\ndef extend():\n    collect_ignore.append("test_y.py")\n\n\nextend()\n',
    b'def extend():\n    global collect_ignore\n    collect_ignore = ["test_y.py"]\n\n\nextend()\n',
    b'class Config:\n    collect_ignore.append("test_y.py")\n',
    b'[collect_ignore for collect_ignore in [["test_y.py"]]]\n',
], ids=["modifyitems", "ignore-hook", "plugins", "star", "imported", "non-literal", "remove", "slice", "loop",
        "attribute", "string-named", "globals", "absolute", "syntax", "unreadable", "function-mutates-module-list",
        "global", "class-body-read", "comprehension-target"])
def test_a_conftest_this_reading_cannot_follow_pays_nothing(conftest):
    assert collector({"tests/conftest.py": conftest})("tests/sub/test_y.py", "test_a") is False


TODAY = datetime.date(2026, 10, 31)
APP = b"def checked(x):\n    if not 0 <= x <= 100:\n        raise ValueError(x)\n    return x\n"
HEAD = "import pytest\nfrom app import checked\n\n\n"
NEGATIVE = "def test_negative():\n    with pytest.raises(ValueError):\n        checked(-1)\n\n\n"
OK = "def test_ok():\n    assert checked(50) == 50\n"


def move(arrival, snapshot, listed=False):
    """Move test_ok out of test_app.py into `arrival` over a head snapshot holding every file."""
    departure = HEAD + NEGATIVE
    changes = [FileChange("test_app.py", "modified", (HEAD + NEGATIVE + OK).encode(), departure.encode()),
               FileChange(arrival, "added", None, (HEAD + OK).encode())]
    head = {"app.py": APP, "test_app.py": departure.encode(), arrival: (HEAD + OK).encode(), **snapshot}
    readers = {}
    if listed:
        readers = {"root_path_lister": lambda: sorted(head),
                   "root_batch_reader": lambda paths: {path: head.get(path) for path in paths}}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=head.get, root_searcher=lambda _: [], **readers)
    return verdict, {f.unit: (f.severity, tuple(f.deescalators)) for f in findings if f.rule == "TEST_DISABLED"}


@pytest.mark.parametrize("arrival,verdict", [
    ("tests/test_moved.py", "pass"),
    ("test_moved.py", "block"),
])
def test_an_arrival_outside_the_testpaths_earns_nothing(arrival, verdict):
    snapshot = {"pytest.ini": b"[pytest]\ntestpaths = tests\n", "tests/test_other.py": b""}
    assert move(arrival, snapshot, listed=True)[0] == verdict


def test_an_arrival_under_an_unreadable_chain_earns_nothing():
    verdict, findings = move("tests/test_moved.py", {"tests/conftest.py": b"collect_ignore = list(range(0))\n"})
    assert verdict == "block" and findings == {"test_ok": ("high", ())}


@pytest.mark.parametrize("snapshot,verdict,expected", [
    ({}, "pass", ("info", ("DUPLICATE_REMAINS",))),
    ({"conftest.py": b'collect_ignore = ["test_copy.py"]\n'}, "block", ("high", ())),
    ({"pytest.ini": b"[pytest]\naddopts = --deselect test_copy.py::test_ok\n"}, "block", ("high", ())),
])
def test_a_surviving_copy_counts_only_where_pytest_runs_it(snapshot, verdict, expected):
    # D10: deleting one of two identical tests leaves the oracle running only
    # if the copy outside the diff is collected.
    departure = HEAD + NEGATIVE
    head = {"app.py": APP, "test_app.py": departure.encode(), "test_copy.py": (HEAD + OK).encode(), **snapshot}
    changes = [FileChange("test_app.py", "modified", (HEAD + NEGATIVE + OK).encode(), departure.encode())]
    _ir, findings, actual = analyze(
        changes, Config(), Contract(), [], TODAY, root_reader=head.get, root_searcher=lambda _: [],
        head_reader=head.get,
        head_searcher=lambda needles: [p for p, data in sorted(head.items()) if any(n.encode() in data for n in needles)])
    assert actual == verdict
    assert {f.unit: (f.severity, tuple(f.deescalators)) for f in findings if f.rule == "TEST_DISABLED"} == {
        "test_ok": expected}


SUITE = HEAD + NEGATIVE + OK


def rename(new, snapshot, old="test_app.py"):
    """`git mv old new`, unchanged, over a head snapshot holding every file."""
    head = {"app.py": APP, new: SUITE.encode(), **snapshot}
    changes = [FileChange(new, "modified", SUITE.encode(), SUITE.encode(), old_path=old)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=head.get, root_searcher=lambda _: [])
    return verdict, {f.unit: f.severity for f in findings if f.rule == "TEST_DISABLED"}


@pytest.mark.parametrize("new,snapshot,old,verdict", [
    # pytest runs no test at head ("no tests ran"); main passed it silently.
    ("app_test.py", {"pytest.ini": b"[pytest]\npython_files = test_*.py\n"}, "test_app.py", "block"),
    ("test_legacy.py", {"conftest.py": b'collect_ignore = ["test_legacy.py"]\n'}, "test_app.py", "block"),
    ("app_test.py", {"pytest.ini": b'[pytest]\npython_files = test_*.py\naddopts = -k "not slow"\n'}, "test_app.py", "block"),
    # Still collected, or never collected under the head's configuration.
    ("app_test.py", {}, "test_app.py", "pass"),
    ("test_other.py", {"pytest.ini": b"[pytest]\npython_files = test_*.py\n"}, "test_app.py", "pass"),
    ("b_test.py", {"pytest.ini": b"[pytest]\npython_files = test_*.py\n"}, "a_test.py", "pass"),
    # An unknown configuration keeps the default reading.
    ("app_test.py", {"pytest.ini": b"[pytest]\npython_files = test_*.py\npython_files = check_*.py\n"}, "test_app.py",
     "pass"),
])
def test_a_rename_the_heads_configuration_stops_collecting_is_a_disappearance(new, snapshot, old, verdict):
    actual, findings = rename(new, snapshot, old)
    assert actual == verdict
    assert findings == ({"test_negative": "high", "test_ok": "high"} if verdict == "block" else {})


# The config is read as pytest 9 loads it: iniconfig's rules for INI files,
# tomllib for TOML, the right section for each file, and addopts alone for
# options. The line reader's spellings these cases use passed or blocked
# where pytest did otherwise.
TOX_K = b'[tox]\nenvlist = py\n\n[testenv]\ncommands =\n    pytest -k "not network" {posargs}\n\n[pytest]\ntestpaths = tests\n'
TOX_O = b"[testenv]\ncommands =\n    pytest -o python_files=*_test.py\n\n[pytest]\npython_files = test_*.py\n"


@pytest.mark.parametrize("files,path,expected", [
    ({"tox.ini": TOX_K, "tests/test_a.py": b""}, "tests/test_x.py", True),  # a tox env's command is no addopts
    ({"tox.ini": TOX_O}, "tests/app_test.py", False),
    ({"pytest.ini": b"[pytest]\n; pytest -k smoke\npython_files = test_*.py\n"}, "test_x.py", True),
    ({"pyproject.toml": b'[tool.pytest.ini_options]\naddopts = """\n    -ra\n    --ignore=tests/legacy\n"""\n'},
     "tests/legacy/test_x.py", False),
    ({"setup.cfg": b"[tool:pytest]\naddopts: --ignore=tests/legacy\n"}, "tests/legacy/test_x.py", False),
    ({"pytest.ini": b"[pytest]  # project settings\npython_files = test_*.py\n"}, "app_test.py", False),
    ({"pyproject.toml": b'[tool.pytest.ini_options]  # pytest\naddopts = "--ignore=legacy"\n'},
     "legacy/test_x.py", False),
    ({"pyproject.toml": b'[tool.pytest.ini_options]\n"addopts" = "--ignore=legacy"\n'}, "legacy/test_x.py", False),
    ({"pyproject.toml": b'[tool.pytest]\nini_options.addopts = "--ignore=legacy"\n'}, "legacy/test_x.py", False),
    # pytest reads [pytest] from pytest.ini, so [tool:pytest] there sets nothing.
    ({"pytest.ini": b"[tool:pytest]\nnorecursedirs = .git\n"}, "CVS/test_x.py", False),
    # pytest keeps an inline comment, and splits a value as a shell would.
    ({"pytest.ini": b"[pytest]\nnorecursedirs = .git build  # legacy\n"}, "legacy/test_x.py", False),
    ({"pytest.ini": b'[pytest]\ntestpaths = "tests" "integration"\n', "integration/test_a.py": b""},
     "integration/test_x.py", True),
    # An empty [tool.pytest] table is no configuration: setup.cfg governs.
    ({"pyproject.toml": b"[tool.pytest]\n", "setup.cfg": b"[tool:pytest]\npython_files = check_*.py\n"},
     "test_x.py", False),
])
def test_the_config_is_read_as_pytest_reads_it(files, path, expected):
    assert collector({**files, path: b""}, listed=True)(path, "test_a") is expected


@pytest.mark.parametrize("files", [
    {"setup.cfg": b"[pytest]\npython_files = check_*.py\n"},  # pytest refuses [pytest] in setup.cfg
    {"pytest.ini": b"[pytest]\naddopts = -ra\n", "setup.cfg": b"[tool:pytest]\nnot a setting\n"},
    {"pyproject.toml": b"\xef\xbb\xbf[tool.pytest.ini_options]\naddopts = \"-ra\"\n"},  # tomllib refuses a BOM
])
def test_a_config_pytest_itself_refuses_decides_nothing(files):
    collected = collector(files)
    assert not collected("test_x.py", "test_a") and not collected.excludes("app_test.py")


@pytest.mark.parametrize("addopts,path,qualname,expected", [
    ("@ci/pytest.args", "tests/test_x.py", "test_a", False),  # argparse reads that file
    ("tests test_moved.py::test_other", "test_moved.py", "test_ok", False),
    ("tests test_moved.py::test_other", "test_moved.py", "test_other", True),
    ("test_moved.py::test_ok[1]", "test_moved.py", "test_ok", False),  # only one of its rows runs
    ("test_moved.py::TestC", "test_moved.py", "TestC.test_ok", True),
    ("--setup-only", "tests/test_x.py", "test_a", False),
    ("--setup-plan", "tests/test_x.py", "test_a", False),
    ("--collectonly", "tests/test_x.py", "test_a", False),
    ("--fixtures", "tests/test_x.py", "test_a", False),
    ("--lf", "tests/test_x.py", "test_a", False),
    ("--sw", "tests/test_x.py", "test_a", False),
    ('-qk "not test_ok"', "tests/test_x.py", "test_a", False),
    ("-p tools.pytest_select", "tests/test_x.py", "test_a", False),
    ("--rootdir=sub", "tests/test_x.py", "test_a", False),
    ("--rootdir=. -ra", "tests/test_x.py", "test_a", True),
    ("-qo python_files=check_*.py", "tests/check_x.py", "test_a", True),
    ("-qo python_files=check_*.py", "tests/test_x.py", "test_a", False),
    # A path-valued option this reading does not know: a directory without a
    # test module is no target, since pytest would collect nothing there.
    ("--mpl-baseline-path tests/baseline", "tests/test_x.py", "test_a", True),
])
def test_addopts_as_pytests_argument_parser_reads_them(addopts, path, qualname, expected):
    files = {**ini("addopts = " + addopts), path: b"", "tests/test_a.py": b"", "tests/baseline/plot.png": b""}
    assert collector(files, listed=True)(path, qualname) is expected


def test_a_node_id_target_keeps_its_file_an_initial_path():
    collected = collector({**ini("addopts = test_moved.py::test_other"), "test_moved.py": b""}, listed=True)
    assert not collected.excludes("test_moved.py")


@pytest.mark.parametrize("settings", [
    "python_files = check_*.py\ntestpaths = tests tests/test_moved.py",
    "python_files = check_*.py\naddopts = tests tests/test_moved.py",
])
def test_pytest_keeps_the_outermost_of_overlapping_initial_paths(settings):
    # tests/test_moved.py is then no initial path and must match python_files.
    files = {**ini(settings), "tests/test_moved.py": b"", "tests/check_a.py": b""}
    assert collector(files, listed=True)("tests/test_moved.py", "test_a") is False


@pytest.mark.parametrize("settings,path,expected", [
    ("norecursedirs = .* */legacy", "legacy/test_x.py", False),  # the absolute path has the checkout above
    ("norecursedirs = .* */legacy", "tests/legacy/test_x.py", False),
    ("python_files = **/test_*.py", "test_moved.py", True),
    ("python_files = **/test_*.py", "tests/test_moved.py", True),
])
def test_a_pattern_with_a_slash_matches_the_absolute_path(settings, path, expected):
    assert collector(ini(settings))(path, "test_a") is expected


@pytest.mark.parametrize("files,path,expected", [
    ({"conftest.py": b'import sys\ncollect_ignore_glob = ["*_py310.py"] if sys.version_info < (3, 10) else []\n'},
     "test_x_py310.py", False),
    ({"conftest.py": b'import sys\ncollect_ignore_glob = ["*_py310.py"] if sys.version_info < (3, 10) else []\n'},
     "test_x.py", True),
    ({"conftest.py": b'import os\ncollect_ignore = [os.path.join("docs", "conf.py"), "setup.py"]\n'},
     "test_x.py", True),
    ({"conftest.py": b'import os\ncollect_ignore = [os.path.join("tests", "test_old.py")]\n'},
     "tests/test_old.py", False),
    ({"conftest.py": b'collect_ignore = ["setup.py"] + ["test_old.py"]\n'}, "test_old.py", False),
    ({"conftest.py": b"import os\nimport settings\n\nos.environ.update({k: str(v) for k, v in vars(settings).items()})\n"},
     "test_x.py", True),
    ({"conftest.py": b'import sys\nvars(sys.modules[__name__]).update(collect_ignore=["test_x.py"])\n'},
     "test_x.py", False),
    ({"conftest.py": b'collect_ignore.append("test_x.py")\n'}, "test_y.py", False),  # its import fails
    # pytest uses the nearest conftest that binds a list; it hides the ones above.
    ({"conftest.py": b'collect_ignore = ["tests/legacy"]\n', "tests/conftest.py": b'collect_ignore = ["test_wip.py"]\n'},
     "tests/legacy/test_values.py", True),
    ({"conftest.py": b'collect_ignore = ["tests/legacy"]\n', "tests/conftest.py": b'collect_ignore = ["test_wip.py"]\n'},
     "tests/test_wip.py", False),
    ({"conftest.py": b'collect_ignore = ["tests/legacy"]\n', "tests/conftest.py": b"import pytest\n"},
     "tests/legacy/test_values.py", False),
    # A coding declaration decides a conftest's text, as it does for Python.
    ({"tests/conftest.py": b"# -*- coding: latin-1 -*-\n# Auteur: Jos\xe9\nimport pytest\n"}, "tests/test_x.py", True),
])
def test_conftest_lists_as_pytest_reads_them(files, path, expected):
    assert collector(files)(path, "test_a") is expected


@pytest.mark.parametrize("files,testpaths,path,expected", [
    # A submodule elsewhere does not make a missing testpath exist.
    (["vendor/", "test_x.py"], "nothere", "test_x.py", True),
    (["vendor/", "test_x.py"], "vendor", "test_x.py", False),
    ([".venv/lib64/", "test_x.py"], "tests/*", "test_x.py", True),
    (["tests/sub/", "test_x.py"], "tests/*", "test_x.py", None),
])
def test_an_opaque_directory_counts_only_where_a_testpath_could_reach_it(files, testpaths, path, expected):
    collected = collector({**ini("testpaths = " + testpaths)}, listed=[*files, "pytest.ini"])
    assert collected(path, "test_a") is (expected is True)
    assert collected.excludes(path) is (expected is False)


def test_a_read_that_fails_in_any_way_is_unknown_and_never_escapes():
    for error in (RuntimeError("symlink loop"), RecursionError(), OSError(), ValueError(), TypeError()):
        collected = collector({"pytest.ini": error})
        assert not collected("test_x.py", "test_a") and not collected.excludes("app_test.py")
        collected = collector({"tests/pyvenv.cfg": error})
        assert not collected("tests/test_x.py", "test_a") and not collected.excludes("tests/test_x.py")


@pytest.mark.parametrize("path", ["/abs/test_x.py", "../test_x.py", "tests//test_x.py", "C:/test_x.py"])
def test_a_path_outside_the_repository_is_unknown(path):
    collection = collector({"conftest.py": b'collect_ignore = ["test_x.py"]\n'})
    assert not collection(path, "test_a") and not collection.excludes(path)


def test_a_deep_path_under_a_recursive_testpath_is_matched_without_recursion():
    path = "tests/" + "a/" * 1500 + "test_x.py"
    assert collector(ini("testpaths = tests/**"))(path, "test_a") is True


@pytest.mark.parametrize("conftest,path,collected,excluded", [
    # An entry added under a condition may not be in the list: neither a
    # credit nor a finding rests on it. An unconditional one is certain.
    (b'import sys\ncollect_ignore = []\nif sys.version_info < (3, 10):\n    collect_ignore.append("test_py310.py")\n',
     "test_py310.py", False, False),
    (b'try:\n    import zoneinfo\nexcept ImportError:\n    collect_ignore = ["test_zones.py"]\n', "test_zones.py", False, False),
    (b'import sys\ncollect_ignore = ["test_old.py"] if sys.version_info < (3, 10) else []\n', "test_old.py", False, False),
    (b'collect_ignore = ["setup.py"]\ncollect_ignore.append("test_old.py")\n', "test_old.py", False, True),
    # A later binding that always runs replaces the list; one that may not
    # leaves the earlier entries only possible.
    (b'collect_ignore = ["test_a.py"]\ncollect_ignore = ["test_b.py"]\n', "test_a.py", True, False),
    (b'import sys\ncollect_ignore = ["test_a.py"]\nif sys.platform == "win32":\n    collect_ignore = []\n',
     "test_a.py", False, False),
])
def test_an_entry_the_module_adds_only_maybe_decides_nothing(conftest, path, collected, excluded):
    collection = collector({"conftest.py": conftest})
    assert collection(path, "test_a") is collected and collection.excludes(path) is excluded


@pytest.mark.parametrize("addopts,path,collected,excluded", [
    # A word after a long option this reading cannot place may be its value.
    ("--some-plugin-flag tests", "other/test_x.py", False, False),
    ("--some-plugin-flag tests", "tests/test_x.py", False, False),
    ("--strict-markers tests", "tests/test_x.py", True, False),
    ("--strict-markers tests", "other/test_x.py", False, True),
    # A --deselect every node id of a file starts with deselects the file.
    ("--deselect tests/legacy", "tests/legacy/test_x.py", False, True),
    ("--deselect tests/test_x.py::test_a", "tests/test_x.py", False, False),
])
def test_addopts_decide_a_file_only_where_certain(addopts, path, collected, excluded):
    files = {**ini("addopts = " + addopts), path: b"", "tests/test_a.py": b""}
    collection = collector(files, listed=True)
    assert collection(path, "test_a") is collected and collection.excludes(path) is excluded


@pytest.mark.parametrize("files,path", [
    ({**ini("addopts = --noconftest"), "conftest.py": b'collect_ignore = ["test_x.py"]\n'}, "test_x.py"),
    ({**ini("addopts = --confcutdir=tests"), "conftest.py": b'collect_ignore = ["tests/test_x.py"]\n'},
     "tests/test_x.py"),
    ({**ini("addopts = --confcutdir=tests"), "conftest.py": b"def pytest_ignore_collect(collection_path):\n    pass\n"},
     "tests/test_x.py"),
    ({**ini("addopts = --collect-in-virtualenv"), "tests/env/pyvenv.cfg": b""}, "tests/env/test_x.py"),
])
def test_options_that_switch_an_exclusion_off_are_read(files, path):
    assert collector(files)(path, "test_a") is True


CLASSES = (b"import unittest\n\n\nclass TestThing:\n    def test_a(self):\n        pass\n\n\n"
           b"class CheckThing:\n    def test_a(self):\n        pass\n\n\n"
           b"class FooTests(unittest.TestCase):\n    def test_a(self):\n        pass\n\n\n"
           b"class BarTests(Base):\n    def test_a(self):\n        pass\n")


@pytest.mark.parametrize("settings,qualname,expected", [
    # Once python_classes is configured, a class it does not take is not
    # collected, unless it may be a TestCase.
    ("python_classes = Check", "TestThing.test_a", False),
    ("python_classes = Check", "CheckThing.test_a", True),
    ("python_classes = Check", "FooTests.test_a", True),
    ("python_classes = Check", "BarTests.test_a", None),
    ("python_classes = Check", "Missing.test_a", None),
    # Left at its default, a class's name and bases are in its proof key,
    # the same on both sides, and are not read again.
    ("python_files = test_*.py", "TestThing.test_a", True),
    ("python_files = test_*.py", "BarTests.test_a", True),
])
def test_a_configured_python_classes_is_read_for_a_class_arrival(settings, qualname, expected):
    collection = collector(ini(settings))
    assert collection("test_x.py", qualname, CLASSES) is (expected is True)


@pytest.mark.parametrize("config,verdict", [(None, "pass"), (b"[pytest]\npython_classes = Check\n", "block")])
def test_a_first_config_that_narrows_python_classes_leaves_a_moved_class_test_unpaid(config, verdict):
    # A first configuration is only a warning, so the class's name being in
    # its proof key on both sides does not keep its collection the same.
    cls = "class TestThing:\n"
    negative = "    def test_negative(self):\n        with pytest.raises(ValueError):\n            checked(-1)\n\n"
    ok = "    def test_ok(self):\n        assert checked(50) == 50\n"
    changes = [FileChange("test_app.py", "modified", (HEAD + cls + negative + ok).encode(), (HEAD + cls + negative).encode()),
               FileChange("test_moved.py", "added", None, (HEAD + cls + ok).encode())]
    head = {"app.py": APP, "test_app.py": (HEAD + cls + negative).encode(), "test_moved.py": (HEAD + cls + ok).encode()}
    if config is not None:
        changes.append(FileChange("pytest.ini", "added", None, config))
        head["pytest.ini"] = config
    _ir, findings, actual = analyze(changes, Config(), Contract(), [], TODAY,
                                    root_reader=head.get, root_searcher=lambda _: [])
    assert actual == verdict
    assert {f.unit: f.severity for f in findings if f.rule == "TEST_DISABLED"} == {
        "TestThing.test_ok": "info" if verdict == "pass" else "high"}


def _git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, input=data).stdout


@pytest.mark.parametrize("files,link", [
    ({"config/pytest.ini": "[pytest]\ntestpaths = tests\n"}, ("pytest.ini", "config/pytest.ini")),
    ({"pytest.ini": "[pytest]\ntestpaths = tests\n", "config/setup.cfg": "[tool:pytest]\naddopts = -ra\n"},
     ("setup.cfg", "config/setup.cfg")),
])
def test_a_root_config_that_is_a_link_is_read_through_it(tmp_path, files, link):
    # pytest follows a linked root config; range mode reads it through the
    # config evidence, where the strict snapshot refuses a link.
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "e2e")
    _git(tmp_path, "config", "user.email", "e2e@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for path, text in {"app.py": APP.decode(), "tests/test_app.py": SUITE, **files}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "-A")
    blob = _git(tmp_path, "hash-object", "-w", "--stdin", data=link[1].encode()).decode().strip()
    _git(tmp_path, "update-index", "--add", "--cacheinfo", f"120000,{blob},{link[0]}")
    _git(tmp_path, "commit", "-m", "base")
    (tmp_path / "tests/test_app.py").write_text(HEAD + NEGATIVE, encoding="utf-8", newline="\n")
    (tmp_path / "tests/test_moved.py").write_text(HEAD + OK, encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "tests/test_app.py", "tests/test_moved.py")
    _git(tmp_path, "commit", "-m", "move test_ok")
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json",
                             "--repo", str(tmp_path)], capture_output=True, text=True,
                            env={**os.environ, "GREENWASH_TODAY": "2026-10-31", "NO_COLOR": "1"})
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["verdict"] == "pass"
    assert {(f["unit"], f["severity"], tuple(f["deescalators"])) for f in report["findings"]
            if f["rule"] == "TEST_DISABLED"} == {("test_ok", "info", ("ASSERTION_MOVED",))}


def test_nothing_is_read_when_no_test_disappeared_or_lost_an_assertion():
    reads = []
    head = {"app.py": APP, "test_app.py": SUITE.encode(), "test_new.py": (HEAD + OK).encode()}

    def read(path):
        reads.append(path)
        return head.get(path)

    analyze([FileChange("test_new.py", "added", None, (HEAD + OK).encode())], Config(), Contract(), [], TODAY,
            root_reader=read, root_searcher=lambda _: [])
    assert not set(reads) & {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.toml"}
