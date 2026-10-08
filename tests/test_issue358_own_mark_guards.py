"""A setup guard that reads the test's own marks is read per unit (#358).

A marker-gated autouse fixture, `if request.node.get_closest_marker("slow")
and not os.environ.get("SLOW"): pytest.skip(...)`, never skips a test without
the `slow` mark. The D6 evaluator cannot read the test's marks, so the guarded
outcome was recorded on every unit the fixture reaches (D-087): a diff that
added such a fixture blocked every test of the module, and a unit carrying it
was not live for D2's move credit.

Ruling 358.Q1-Q3 (2026-10-08): each path condition is read against the marks
the unit carries statically before the paths are joined (`own_marks.resolve`).
The marks are unknown, and the guard is read as before, wherever a mark may be
added that this reading cannot see.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.own_marks import UNKNOWN, OwnMarks, adds_marks, reads_marks, resolve

PATH = "tests/test_billing.py"
APP = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
GATE = (
    "@pytest.fixture(autouse=True)\n"
    "def only_slow(request):\n"
    "    if request.node.get_closest_marker('slow') and not os.environ.get('SLOW'):\n"
    "        pytest.skip('slow tests are off')\n\n\n"
)


def module(tests="def test_total():\n    assert total() == 78.75\n", gate=GATE, prelude=""):
    return f"import os\n\nimport pytest\n\nfrom app.billing import total\n{prelude}\n\n{gate}{tests}"


def setup_markers(source, chain=()):
    parsed = parse_python(source.encode(), collect_tests=True, chain=chain)
    return {u.qualname: [(m.name, m.guard) for m in u.side.markers if m.name.startswith("setup.")]
            for u in parsed.units}


def run(before, after, *, files=None, root=True):
    """TEST_DISABLED (message, severity) and the verdict for one test module edit."""
    snapshot = {**APP, PATH: after.encode(), **(files or {})}
    _ir, findings, verdict = analyze(
        [FileChange(PATH, "modified", before.encode(), after.encode())], Config(), Contract(), [],
        datetime.date(2026, 10, 8), head_reader=snapshot.get, root_reader=snapshot.get if root else None,
    )
    return [(f.message, f.severity) for f in findings if f.rule == "TEST_DISABLED"], verdict


def marks(source, func="test_total", classes=()):
    tree = ast.parse(source)
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    return OwnMarks(tree).of(defs[func], tuple(defs[c] for c in classes))


# --- one path condition, read against the unit's marks --------------------------------------

READ = "request.node.get_closest_marker('slow')"
PATH_X = ("skip", "evidence", (f"{READ}", "not os.environ.get('SLOW')"))


@pytest.mark.parametrize("cond, carried, expected", [
    (READ, {"slow"}, ("skip", "evidence", None)),
    (READ, set(), None),
    (f"not ({READ})", set(), ("skip", "evidence", None)),
    (f"not ({READ})", {"slow"}, None),
    (f"{READ} is not None", {"slow"}, ("skip", "evidence", None)),
    (f"{READ} is None", {"slow"}, None),
    (f"bool({READ})", set(), None),
    ("request.node.get_marker('slow')", set(), None),
    ("request.node.get_closest_marker(name='slow')", set(), None),
    # not the test's own marks, or not a plain presence read: kept as written
    ("item.get_closest_marker('slow')", set(), ("skip", "evidence", "item.get_closest_marker('slow')")),
    (f"{READ} is False", set(), ("skip", "evidence", f"{READ} is False")),
    ("request.node.get_closest_marker('slow', default)", set(),
     ("skip", "evidence", "request.node.get_closest_marker('slow', default)")),
])
def test_a_marks_read_is_settled_by_the_units_marks(cond, carried, expected):
    assert resolve((("skip", "evidence", (cond,)),), frozenset(carried), frozenset({"test_total"})) == expected


def test_a_settled_condition_leaves_the_rest_of_its_path():
    assert resolve((PATH_X,), frozenset({"slow"}), frozenset()) == ("skip", "evidence", "not os.environ.get('SLOW')")
    assert resolve((PATH_X,), frozenset(), frozenset()) is None


def test_unknown_marks_keep_the_condition_as_written():
    assert resolve((PATH_X,), UNKNOWN, frozenset()) == (
        "skip", "evidence", f"{READ} and not os.environ.get('SLOW')")


@pytest.mark.parametrize("cond, carried, expected", [
    # pytest's keywords also hold the test's, its classes', module's and directories' names.
    ("'slow' in request.keywords", {"slow"}, ("skip", "e", None)),
    ("'test_total' in request.keywords", set(), ("skip", "e", None)),
    ("'slow' in request.keywords", set(), ("skip", "e", "'slow' in request.keywords")),
    ("'slow' not in request.keywords", {"slow"}, None),
    ("request.keywords.get('slow')", {"slow"}, ("skip", "e", None)),
    ("request.node.keywords.get('slow')", set(), ("skip", "e", "request.node.keywords.get('slow')")),
])
def test_a_keywords_read_is_true_only_when_provable(cond, carried, expected):
    assert resolve((("skip", "e", (cond,)),), frozenset(carried), frozenset({"test_total"})) == expected


def test_each_path_keeps_its_own_effect():
    paths = (("xfail", "a", ("request.node.get_closest_marker('a')",)),
             ("skip", "b", ("request.node.get_closest_marker('b')",)))
    assert resolve(paths, frozenset({"b"}), frozenset()) == ("skip", "b", None)
    assert resolve(paths, frozenset({"a", "b"}), frozenset()) == ("xfail", "a", None)
    assert resolve(paths, frozenset(), frozenset()) is None


def test_two_surviving_paths_are_joined_as_setup_outcome_joins_them():
    paths = (("skip", "a", ("request.node.get_closest_marker('a')", "X")), ("skip", "b", ("Y",)))
    assert resolve(paths, frozenset({"a"}), frozenset()) == ("skip", "a", "(X) or (Y)")


def test_a_condition_that_is_no_expression_stays():
    paths = (("skip", "e", (f"not (not {READ})", "except ImportError")),)
    assert resolve(paths, frozenset({"slow"}), frozenset()) == ("skip", "e", "except ImportError")
    assert resolve(paths, frozenset(), frozenset()) is None


def test_the_screen_only_passes_a_request_read():
    assert reads_marks(READ) and reads_marks("'x' in request.keywords")
    assert not reads_marks("not os.environ.get('SLOW')") and not reads_marks(None)


# --- the marks a unit carries ---------------------------------------------------------------


@pytest.mark.parametrize("source, expected", [
    ("import pytest\n@pytest.mark.slow\ndef test_total(): pass\n", {"slow"}),
    ("import pytest as pt\n@pt.mark.slow(reason='x')\ndef test_total(): pass\n", {"slow"}),
    ("from pytest import mark\n@mark.slow\ndef test_total(): pass\n", {"slow"}),
    ("import pytest\nslow = pytest.mark.slow\n@slow\ndef test_total(): pass\n", {"slow"}),
    ("import pytest\npytestmark = pytest.mark.db\ndef test_total(): pass\n", {"db"}),
    ("import pytest\npytestmark = [pytest.mark.db, pytest.mark.net]\ndef test_total(): pass\n", {"db", "net"}),
    ("import pytest\npytestmark = [pytest.mark.db]\npytestmark += [pytest.mark.net]\ndef test_total(): pass\n",
     {"db", "net"}),
    ("from unittest import mock\n@mock.patch('x')\ndef test_total(m): pass\n", set()),
    ("from unittest.mock import patch\n@patch('x')\ndef test_total(m): pass\n", set()),
    ("from twisted.internet import defer\n@defer.inlineCallbacks\ndef test_total(): pass\n", set()),
    ("import pytest\n@pytest.mark.parametrize('x', [1, 2])\ndef test_total(x): pass\n", {"parametrize"}),
    # the final binding of `pytestmark` is the one pytest reads
    ("import pytest\npytestmark = [pytest.mark.db]\npytestmark = [pytest.mark.net]\ndef test_total(): pass\n", {"net"}),
    ("import pytest\nmark = pytest.mark\n@mark.slow\ndef test_total(): pass\n", {"slow"}),
    ("import py\n@py.test.mark.slow\ndef test_total(): pass\n", {"slow"}),
    ("import pytest\nCASES = [1, 2]\n@pytest.mark.parametrize('x', CASES)\ndef test_total(x): pass\n", {"parametrize"}),
    ("import pytest\nfrom app.cases import CASES\n@pytest.mark.parametrize('x', CASES)\ndef test_total(x): pass\n",
     {"parametrize"}),
    ("import pytest\ndef ids(x): return str(x)\n@pytest.mark.parametrize('x', [pytest.param(1)], ids=ids)\n"
     "def test_total(x): pass\n", {"parametrize"}),
])
def test_static_marks_are_read(source, expected):
    assert marks(source) == frozenset(expected)


@pytest.mark.parametrize("source", [
    # a mark that may be added where this reading cannot see it
    "import pytest\nif X:\n    pytestmark = pytest.mark.db\ndef test_total(): pass\n",
    "import pytest\npytestmark = []\npytestmark.append(pytest.mark.db)\ndef test_total(): pass\n",
    "import pytest\npytestmark = make_marks()\ndef test_total(): pass\n",
    "import pytest\n@pytest.mark.parametrize('x', [pytest.param(1, marks=pytest.mark.slow)])\n"
    "def test_total(x): pass\n",
    "from tests.marks import slow\n@slow\ndef test_total(): pass\n",
    "from .marks import slow\n@slow\ndef test_total(): pass\n",
    "from tests import marks\n@marks.slow\ndef test_total(): pass\n",
    "import pytest\n@pytest.fixture(autouse=True)\ndef f(request):\n    request.applymarker(pytest.mark.slow)\n"
    "def test_total(): pass\n",
    "def pytest_generate_tests(metafunc): pass\ndef test_total(): pass\n",
    "a = b\nb = a\n@a\ndef test_total(): pass\n",
    # a same-file decorator may apply a mark in its body; a plugin may mark what its decorator wraps
    "def deco(f): return f\n@deco\ndef test_total(): pass\n",
    "from hypothesis import given\n@given(x=1)\ndef test_total(x): pass\n",
    # an async plugin in auto mode marks each coroutine test
    "import pytest\n@pytest.mark.slow\nasync def test_total(): pass\n",
    # a param with marks reached through a name, a mapping or another module
    "import pytest\nCASES = [pytest.param(1, marks=pytest.mark.slow)]\n@pytest.mark.parametrize('x', CASES)\n"
    "def test_total(x): pass\n",
    "import pytest\n@pytest.mark.parametrize('x', [pytest.param(1, **KW)])\ndef test_total(x): pass\n",
    "import pytest\nfrom tests.cases import CASES\n@pytest.mark.parametrize('x', CASES)\ndef test_total(x): pass\n",
    "import pytest\nfrom .cases import make\n@pytest.mark.parametrize('x', make())\ndef test_total(x): pass\n",
    "import pytest\nfrom tests.cases import *\n@pytest.mark.parametrize('x', CASES)\ndef test_total(x): pass\n",
    # a name bound more than once, or by a statement this reading does not follow
    "import pytest\nslow = pytest.mark.slow\nslow = pytest.mark.fast\n@slow\ndef test_total(): pass\n",
    "try:\n    from pytest import mark\nexcept ImportError:\n    mark = None\n@mark.slow\ndef test_total(): pass\n",
    "from tests.marks import *\n@slow\ndef test_total(): pass\n",
    "import pytest\ndef test_total(): pass\ntest_total = pytest.mark.slow(test_total)\n",
    "import pytest\npytestmark = [pytest.mark.db]\npytestmark *= 2\ndef test_total(): pass\n",
    "import pytest\nslow = pytest.mark.skipif(True)\n@slow('x')\ndef test_total(): pass\n",
    "import pytest\nfrom tests.cases import BASE\nCASES = BASE + [1]\n@pytest.mark.parametrize('x', CASES)\n"
    "def test_total(x): pass\n",
])
def test_a_mark_this_reading_cannot_see_leaves_the_marks_unknown(source):
    assert marks(source) is UNKNOWN


def test_class_marks_and_same_file_bases_count():
    source = (
        "import unittest\nimport pytest\n\n@pytest.mark.db\nclass Base:\n    pytestmark = [pytest.mark.net]\n\n"
        "class TestX(Base, unittest.TestCase):\n    @pytest.mark.slow\n    def test_total(self): pass\n"
    )
    assert marks(source, classes=("TestX",)) == frozenset({"db", "net", "slow"})


def test_a_class_body_alias_leaves_the_marks_unknown():
    """A decorator in a class body sees the class's names first."""
    source = "import pytest\n\nclass TestX:\n    slow = pytest.mark.slow\n\n    @slow\n    def test_total(self): pass\n"
    assert marks(source, classes=("TestX",)) is UNKNOWN


@pytest.mark.parametrize("subclass", [
    "class TestX(Base):\n    pytestmark = [pytest.mark.net]\n    def test_total(self): pass\n",
    "class TestX(Base, Other):\n    def test_total(self): pass\n",
])
def test_inherited_marks_that_pytest_before_7_2_reads_otherwise_are_unknown(subclass):
    """Before 7.2 a class read its own `pytestmark`, or its first marked base's, not the MRO's."""
    source = ("import pytest\n\n@pytest.mark.db\nclass Base:\n    pass\n\n@pytest.mark.web\nclass Other:\n    pass\n\n"
              + subclass)
    assert marks(source, classes=("TestX",)) is UNKNOWN


def test_a_base_from_another_module_leaves_the_marks_unknown():
    source = "from tests.base import Base\n\nclass TestX(Base):\n    def test_total(self): pass\n"
    assert marks(source, classes=("TestX",)) is UNKNOWN


def test_a_conftest_that_may_add_marks_leaves_them_unknown():
    hook = "def pytest_collection_modifyitems(items):\n    pass\n"
    assert adds_marks(ast.parse(hook)) and adds_marks(ast.parse("pytest_plugins = ['x']\n"))
    assert not adds_marks(ast.parse("import pytest\n\n@pytest.fixture\ndef f():\n    return 1\n"))

    class Level:
        adds_marks = True

    tree = ast.parse("def test_total(): pass\n")
    assert OwnMarks(tree, (Level(),)).of(tree.body[0]) is UNKNOWN


# --- what the unit records ------------------------------------------------------------------


def test_an_unmarked_unit_records_no_marker_and_a_marked_one_keeps_the_rest_of_the_guard():
    tests = ("def test_total():\n    assert total() == 78.75\n\n\n"
             "@pytest.mark.slow\ndef test_slow():\n    assert total() == 78.75\n")
    assert setup_markers(module(tests)) == {
        "test_total": [],
        "test_slow": [("setup.only_slow.skip", "not os.environ.get('SLOW')")],
    }


def test_a_class_mark_reaches_the_method():
    tests = ("@pytest.mark.slow\nclass TestBilling:\n    def test_total(self):\n        assert total() == 78.75\n")
    assert setup_markers(module(tests)) == {
        "TestBilling.test_total": [("setup.only_slow.skip", "not os.environ.get('SLOW')")]}


@pytest.mark.parametrize("gate", [
    # a wider scope's `request.node` is the module, not the test
    "@pytest.fixture(scope='module', autouse=True)\ndef only_slow(request):\n",
    "@pytest.fixture(scope=SCOPE, autouse=True)\ndef only_slow(request):\n",
    # no `request` of its own: the name is the module's
    "@pytest.fixture(autouse=True)\ndef only_slow():\n",
    "@pytest.fixture(autouse=True)\ndef only_slow(request):\n    request = other\n",
])
def test_a_guard_whose_request_is_not_the_tests_is_read_as_before(gate):
    gate += ("    if request.node.get_closest_marker('slow') and not os.environ.get('SLOW'):\n"
             "        pytest.skip('slow tests are off')\n\n\n")
    assert setup_markers(module(gate=gate)) == {"test_total": [
        ("setup.only_slow.skip", "request.node.get_closest_marker('slow') and not os.environ.get('SLOW')")]}


def test_the_default_scope_spelled_out_is_read_per_unit():
    gate = GATE.replace("autouse=True", "autouse=True, scope='function'")
    assert setup_markers(module(gate=gate)) == {"test_total": []}


def test_the_keywords_hold_the_class_name():
    gate = ("@pytest.fixture(autouse=True)\ndef not_billing(request):\n"
            "    if 'TestBilling' in request.keywords:\n        pytest.skip('elsewhere')\n\n\n")
    tests = "class TestBilling:\n    def test_total(self):\n        assert total() == 78.75\n"
    assert setup_markers(module(tests, gate=gate)) == {"TestBilling.test_total": [("setup.not_billing.skip", None)]}


def test_a_gate_on_an_absent_mark_is_unconditional_for_the_unit():
    gate = ("@pytest.fixture(autouse=True)\ndef needs_fast(request):\n"
            "    if not request.node.get_closest_marker('fast'):\n        pytest.skip('fast only')\n\n\n")
    assert setup_markers(module(gate=gate)) == {"test_total": [("setup.needs_fast.skip", None)]}


# --- how it is judged -----------------------------------------------------------------------


def test_adding_a_marker_gated_fixture_is_quiet_for_unmarked_tests():
    """The issue's reproduction: main blocked `test_total`, which pytest runs."""
    assert run(module(gate=""), module()) == ([], "pass")


def test_a_test_newly_marked_under_the_gate_is_a_disable():
    after = module("@pytest.mark.slow\ndef test_total():\n    assert total() == 78.75\n")
    found, verdict = run(module(), after)
    assert verdict == "block"
    assert found == [("test_total: skip/xfail added to the setup this test runs (setup.only_slow.skip)", "high")]


def test_a_hook_that_may_add_marks_keeps_the_old_reading():
    """358.Q2: unknown, failing toward flagging."""
    conftest = "def pytest_collection_modifyitems(items):\n    pass\n"
    found, verdict = run(module(gate=""), module(), files={"tests/conftest.py": conftest.encode()})
    assert verdict == "block" and [severity for _message, severity in found] == ["high"]


def test_a_conftest_that_cannot_be_read_keeps_the_old_reading():
    found, verdict = run(module(gate=""), module(), files={"tests/conftest.py": b"def broken(:\n"})
    assert verdict == "block" and [severity for _message, severity in found] == ["high"]


def test_a_test_moved_under_the_gate_keeps_its_move_credit():
    """An unmarked test carries no marker, so its arrival is live (D2)."""
    body = "def test_total():\n    assert total() == 78.75\n"
    other = "tests/test_other.py"
    after = module(tests="")
    moved = module(tests=body)
    snapshot = {**APP, PATH: after.encode(), other: moved.encode()}
    _ir, findings, verdict = analyze(
        [FileChange(PATH, "modified", module().encode(), after.encode()),
         FileChange(other, "added", None, moved.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 8), head_reader=snapshot.get, root_reader=snapshot.get,
    )
    assert verdict == "pass"
    assert not [f for f in findings if f.severity == "high"]
