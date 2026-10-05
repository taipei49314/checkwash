"""Only an effect makes a collection hook a control (#209 Q2), and a module
`pytestmark` is read as the call it holds (#209 X1).

209.Q2: a `pytest_collection_modifyitems` that sorted its items, or marked them
with a mark that is neither skip nor xfail, blocked at high as a suite-level
control. Only an effect that can drop or disable an item counts now; one this
reading cannot read still does.

X1: a `pytestmark` mark was recorded with the whole assignment as its text,
which never parsed as a call, so D6 could not read a `skipif` condition there:
`pytestmark = pytest.mark.skipif(sys.platform == "win32")` blocked at high
while the same decorator held at warn.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint
from checkwash.frontends.python import frontend as F
from checkwash.frontends.python.conftest_controls import COLLECTION_NAMES, SKIP_MARK, is_collection_control, marker_kind
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.hook_guards import collection_hook_guards
from checkwash.ir.markers import marker_call

CONFTEST = "tests/conftest.py"
TEST_PATH = "tests/test_calc.py"
HEAD = "import importlib.util\nimport os\nimport sys\n\nimport pytest\n\n"
BILLING = b"def total():\n    return 78.75\n"
MODIFYITEMS = "conftest.pytest_collection_modifyitems"
IGNORE = "conftest.pytest_ignore_collect"
ADD_MARKER = "conftest.add_marker_skip"


class _Text:
    def __init__(self, text):
        self.text = text

    def seg(self, node):
        return ast.get_source_segment(self.text, node)


def suite(source):
    """The `<suite>` markers of a conftest, with their guards."""
    unit = F._conftest_unit(ast.parse(source), _Text(source), F._Offsets(source))
    return {m.name: m.guard for m in unit.side.markers}


def hook(body, name="pytest_collection_modifyitems", params="config, items"):
    lines = "".join(f"    {line}\n" if line else "\n" for line in body.split("\n"))
    return HEAD + f"\ndef {name}({params}):\n{lines}"


def analyze_change(*changes):
    _ir, findings, verdict = analyze(
        list(changes), Config(), Contract(), [], datetime.date(2026, 10, 5),
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def conftest_added(source):
    return analyze_change(FileChange(CONFTEST, "modified", HEAD.encode(), source.encode()))


# --- 209.Q2: a reorder or a labelling mark is no effect -------------------------

NO_EFFECT = {
    "sort": "items.sort(key=lambda item: item.nodeid)",
    "sort_reverse": "items.sort(key=str, reverse=True)",
    "reverse": "items.reverse()",
    "sorted_slice": "items[:] = sorted(items, key=lambda item: item.get_closest_marker('order') is None)",
    "reversed_slice": "items[:] = list(reversed(items))",
    "label": "for item in items:\n    item.add_marker(pytest.mark.timeout(30))",
    "label_by_name": 'for item in items:\n    if "network" in item.nodeid:\n        item.add_marker("network")',
    "label_bound_once": "slow = pytest.mark.slow\nfor item in items:\n    item.add_marker(slow, append=False)",
    "label_from_mark": "from pytest import mark\nfor item in items:\n    item.add_marker(mark.flaky(reruns=2))",
    "nothing": "pass",
    "reads_only": 'print("collected", len(items))\nreturn None',
}


@pytest.mark.parametrize("body", NO_EFFECT.values(), ids=NO_EFFECT.keys())
def test_a_hook_with_no_effect_that_drops_or_disables_is_not_a_control(body):
    markers = suite(hook(body))
    assert MODIFYITEMS not in markers
    assert ADD_MARKER not in markers


@pytest.mark.parametrize("body", NO_EFFECT.values(), ids=NO_EFFECT.keys())
def test_such_a_hook_reports_nothing(body):
    found, verdict = conftest_added(hook(body))
    assert found == []
    assert verdict == "pass"


EFFECT = {
    # a mark that names skip or xfail, or runs code at setup, or skips on another test's outcome
    "skip": "for item in items:\n    item.add_marker(pytest.mark.skip)",
    "skip_by_name": 'for item in items:\n    item.add_marker("skip")',
    "skipif_by_name": 'for item in items:\n    item.add_marker("skipif")',
    "xfail": "for item in items:\n    item.add_marker(pytest.mark.xfail(run=False))",
    "plugin_skip": "for item in items:\n    item.add_marker(pytest.mark.skip_on_windows)",
    "usefixtures": 'for item in items:\n    item.add_marker(pytest.mark.usefixtures("offline"))',
    "dependency": 'for item in items:\n    item.add_marker(pytest.mark.dependency(depends=["test_login"]))',
    # a mark this reading cannot name
    "unknown_mark": "for item, mark in zip(items, MARKS):\n    item.add_marker(mark)",
    "mark_with_effect": "for item in items:\n    item.add_marker(pytest.mark.timeout(items.pop()))",
    "unimported_mark": "for item in items:\n    item.add_marker(other.mark.slow)",
    "pytest_rebound": "pytest = FAKE\nfor item in items:\n    item.add_marker(pytest.mark.slow)",
    # a key that acts on every item, or one this reading cannot see into
    "sort_key_acts": "items.sort(key=items.remove)",
    "sort_key_built": "import operator\nitems.sort(key=operator.attrgetter('nodeid'))",
    "sorted_key_acts": "items[:] = sorted(items, key=items.remove)",
    # not the list pytest passed, not all of it, or not a reorder
    "rebound_items": "items = list(items)\nitems.sort()",
    "session_items": "session.items.sort()",
    "partial_slice": "items[1:] = sorted(items[1:])",
    "other_list": "items[:] = sorted(KEEP)",
    "shuffle": "import random\nrandom.shuffle(items)",
    "filtered": "items[:] = [item for item in items if 'slow' not in item.keywords]",
    "slice_from_one": "items[1:] = sorted(items)",
    "list_of_part": "items[:] = list(items[:1])",
    "reversed_other": "items[:] = reversed(KEEP)",
    "reverse_with_keyword": "items.reverse(reverse=True)",
    # a receiver, an argument or a keyword that acts itself
    "receiver_acts": "items.pop().add_marker(pytest.mark.slow)",
    "append_acts": "for item in items:\n    item.add_marker(pytest.mark.slow, append=items.clear())",
    "not_a_mark": "for item in items:\n    item.add_marker(os.path.basename)",
    # a name that differs only in case is read as the name it spells
    "skip_capitalised": 'for item in items:\n    item.add_marker("Skip")',
    # `items` bound to something else first
    "deleted_then_sorted": "del items\nitems.sort()",
    "imported_as_items": "import collections as items\nitems.sort()",
    "defined_as_items": "def items():\n    pass\nitems.sort()",
    "caught_as_items": "try:\n    pass\nexcept Exception as items:\n    pass\nitems.sort()",
    "captured_as_items": "match KEEP:\n    case [*items]:\n        pass\nitems.sort()",
}


@pytest.mark.parametrize("body", EFFECT.values(), ids=EFFECT.keys())
def test_an_effect_that_can_drop_or_disable_makes_the_hook_a_control(body):
    params = "session, config, items" if "session" in body else "config, items"
    assert suite(hook(body, params=params))[MODIFYITEMS] is None


@pytest.mark.parametrize("module, body", [
    ("def sorted(items, key=None):\n    items.clear()\n", "items[:] = sorted(items)"),
    ("def reversed(items):\n    items.clear()\n", "items[:] = reversed(items)"),
    ("def list(items):\n    items.clear()\n", "items[:] = list(reversed(items))"),
    ("from helpers import *\n", "items[:] = sorted(items)"),
])
def test_a_reorder_through_a_rebound_builtin_is_an_effect(module, body):
    assert MODIFYITEMS not in suite(HEAD + hook(body).replace(HEAD, "", 1))
    assert suite(module + hook(body))[MODIFYITEMS] is None


def test_a_reorder_beside_a_guarded_effect_keeps_its_guard():
    body = (
        "items.sort(key=lambda item: item.nodeid)\n"
        'if not os.environ.get("NETWORK"):\n'
        "    for item in items:\n"
        '        if "network" in item.keywords:\n'
        '            item.add_marker(pytest.mark.skip(reason="offline"))'
    )
    assert suite(hook(body)) == {MODIFYITEMS: 'not os.environ.get("NETWORK")', ADD_MARKER: 'not os.environ.get("NETWORK")'}


def test_a_labelling_mark_beside_an_unguarded_skip_leaves_the_hook_unguarded():
    body = "for item in items:\n    item.add_marker(pytest.mark.timeout(30))\n    item.add_marker(pytest.mark.skip)"
    assert suite(hook(body)) == {MODIFYITEMS: None, ADD_MARKER: None}


@pytest.mark.parametrize("body, control", [
    ("return False", False),
    ("return None", False),
    ("pass", False),
    ('if os.environ.get("NETWORK"):\n    return False', False),
    ("return True", True),
    ('return collection_path.name == "test_legacy.py"', True),
])
def test_an_ignore_collect_hook_is_a_control_when_it_can_return_true(body, control):
    markers = suite(hook(body, name="pytest_ignore_collect", params="collection_path, config"))
    assert (IGNORE in markers) is control


def test_the_reader_and_the_frontend_agree_on_which_hooks_are_controls():
    source = hook("items.sort()") + "\n\n" + hook("items[:] = []", name="pytest_ignore_collect",
                                                    params="collection_path, config").replace(HEAD, "")
    tree = ast.parse(source)
    hooks, _calls = collection_hook_guards(tree, ast.unparse)
    named = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and id(node) in hooks}
    assert named == {"pytest_ignore_collect"}
    assert set(suite(source)) == {IGNORE}


def test_a_hook_that_gains_its_first_effect_is_reported():
    before = hook("items.sort()")
    after = hook("items.sort()\nitems[:] = items[:1]")
    found, verdict = analyze_change(FileChange(CONFTEST, "modified", before.encode(), after.encode()))
    assert [(f.unit, f.message.rsplit("(", 1)[1], f.severity) for f in found] == [
        ("<suite>", MODIFYITEMS + ")", "high")]
    assert verdict == "block"


# --- 209.Q3: a conftest's `pytestmark` is not a collection control ---------------

def test_a_skip_mark_is_not_a_collection_control():
    assert marker_kind("pytest.mark.skip") == SKIP_MARK
    assert not is_collection_control("pytest.mark.skip")
    assert not is_collection_control('pytest.mark.skipif(sys.platform=="win32")')
    assert all(is_collection_control(name) for name in COLLECTION_NAMES)


# --- X1: a module `pytestmark` is read as the call it holds ----------------------

def module_markers(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    return parsed.units[0].side.markers


@pytest.mark.parametrize("assignment, texts", [
    ('pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="posix only")',
     ['pytest.mark.skipif(sys.platform == "win32", reason="posix only")']),
    ("pytestmark = pytest.mark.skip", ["pytest.mark.skip"]),
    ('pytestmark = [pytest.mark.slow, pytest.mark.skipif(sys.platform == "win32"), pytest.mark.xfail]',
     ['pytest.mark.skipif(sys.platform == "win32")', "pytest.mark.xfail"]),
])
def test_a_pytestmark_mark_records_its_own_call(assignment, texts):
    source = f"import sys\n\nimport pytest\n\n{assignment}\n\n\ndef test_add():\n    assert 1 + 1 == 2\n"
    markers = module_markers(source)
    assert [m.text for m in markers] == texts
    for m in markers:
        assert source[m.span[0]:m.span[1]] == m.text
        # A mark written as a call parses as one, which is what D6 reads.
        assert ("(" in m.text) == (marker_call(m.text) is not None)


def test_a_pytestmark_name_keeps_its_identity():
    source = ('import sys\n\nimport pytest\n\npytestmark = pytest.mark.skipif(sys.platform == "win32")\n\n\n'
              "def test_add():\n    assert 1 + 1 == 2\n")
    decorated = ('import sys\n\nimport pytest\n\n\n@pytest.mark.skipif(sys.platform == "win32")\n'
                 "def test_add():\n    assert 1 + 1 == 2\n")
    assert [m.name for m in module_markers(source)] == [m.name for m in module_markers(decorated)]


BEFORE = "import sys\n\nimport pytest\n\nWIN = sys.platform == 'win32'\n\n\ndef test_add():\n    assert 1 + 1 == 2\n"


def with_pytestmark(assignment):
    return BEFORE.replace("\n\n\ndef test_add", f"\n\n{assignment}\n\n\ndef test_add")


@pytest.mark.parametrize("assignment, outcome", [
    # X1 and X2: the module mark and the decorator are judged alike
    ('pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="posix only")', ("warn", ["COMPAT_GATE"], "pass")),
    ('pytestmark = [pytest.mark.slow, pytest.mark.skipif(sys.platform == "win32")]', ("warn", ["COMPAT_GATE"], "pass")),
    # a module constant in the condition is resolved as a decorator's is
    ("pytestmark = pytest.mark.skipif(WIN, reason='posix only')", ("warn", ["COMPAT_GATE"], "pass")),
    ('pytestmark = pytest.mark.xfail(sys.platform == "win32", reason="flaky there")', ("warn", ["COMPAT_GATE"], "pass")),
    # an always-true condition, a strict xfail and a bare skip still block
    ("pytestmark = pytest.mark.skipif(sys.version_info >= (3, 0), reason='later')", ("high", [], "block")),
    ('pytestmark = pytest.mark.xfail(sys.platform == "win32", strict=True)', ("high", [], "block")),
    ("pytestmark = pytest.mark.skip(reason='later')", ("high", [], "block")),
])
def test_d6_reads_a_pytestmark_condition(assignment, outcome):
    after = with_pytestmark(assignment)
    found, verdict = analyze_change(FileChange(TEST_PATH, "modified", BEFORE.encode(), after.encode()))
    assert [(f.unit, f.severity, f.deescalators) for f in found] == [("test_add", *outcome[:2])]
    assert verdict == outcome[2]


def test_the_fingerprint_is_the_marker_name_s():
    after = with_pytestmark('pytestmark = pytest.mark.skipif(sys.platform == "win32")')
    found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", BEFORE.encode(), after.encode()))
    (finding,) = found
    assert finding.fingerprint == make_fingerprint(
        "TEST_DISABLED", TEST_PATH, "test_add", 'pytest.mark.skipif(sys.platform=="win32")')
    assert finding.after.text == 'pytest.mark.skipif(sys.platform == "win32")'
