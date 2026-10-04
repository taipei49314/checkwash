"""A conftest collection hook carries the condition its effects fire under (#209 Q1),
and D6 judges the marker a finding reports (#208).

#209: a `pytest_collection_modifyitems` or `pytest_ignore_collect` hook, and an
`add_marker` skip, was a suite-level control whatever its body did, with no
guard, so pytest's own `--runslow` recipe blocked at high while the same
condition on `collect_ignore` held at warn. #208: D6 held a new disable at
warn when any marker on the same unit was a qualified gate, so an honest gate
lent its credit to an unconditional disable beside it.

This file pins the reading (`hook_guards`), the helpers D6 uses
(`finding_marker`, `compat_gate_for`), and what follows from a hook guard on
its own: a guard edited to one that always holds is reported.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.compat import compat_gate_for, guard_can_be_false
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.test_disabled import finding_marker
from checkwash.engine import analyze
from checkwash.frontends.python import frontend as F
from checkwash.frontends.python.hook_guards import weakest

CONFTEST = "tests/conftest.py"
TEST_PATH = "tests/test_billing.py"
HEAD = "import importlib.util\nimport os\nimport sys\n\nimport pytest\n\n"
BILLING = b"def total():\n    return 78.75\n"


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


MODIFYITEMS = "conftest.pytest_collection_modifyitems"
IGNORE = "conftest.pytest_ignore_collect"
ADD_MARKER = "conftest.add_marker_skip"

RUNSLOW = (
    'if config.getoption("--runslow"):\n'
    "    return\n"
    'skip_slow = pytest.mark.skip(reason="need --runslow option to run")\n'
    "for item in items:\n"
    '    if "slow" in item.keywords:\n'
    "        item.add_marker(skip_slow)"
)
NETWORK = (
    'if not os.environ.get("NETWORK"):\n'
    '    skip_network = pytest.mark.skip(reason="set NETWORK=1 to run")\n'
    "    for item in items:\n"
    '        if "network" in item.keywords:\n'
    "            item.add_marker(skip_network)"
)


# --- the condition a hook acts under ------------------------------------------

@pytest.mark.parametrize("body, guard", [
    # pytest's own recipe: the code after a branch that always returns.
    (RUNSLOW, 'not (config.getoption("--runslow"))'),
    (NETWORK, 'not os.environ.get("NETWORK")'),
    ('if importlib.util.find_spec("redis") is None:\n'
     "    for item in items:\n"
     '        if "redis" in item.nodeid:\n'
     "            items.remove(item)",
     'importlib.util.find_spec("redis") is None'),
    # Recorded as written; D6 refuses a guard that always holds.
    ("if sys.version_info >= (3, 0):\n    items[:] = []", "sys.version_info >= (3, 0)"),
    ("if sys.version_info < (3, 0):\n    return\nitems[:] = []", "not (sys.version_info < (3, 0))"),
    ("if True:\n    items[:] = []", None),
    # `else`, a nested `if`, and `continue` in a loop.
    ('if os.environ.get("NETWORK"):\n    pass\nelse:\n    items[:] = []', 'not (os.environ.get("NETWORK"))'),
    ('if sys.platform == "win32":\n    if not os.environ.get("CI"):\n        items[:] = []',
     'sys.platform == "win32" and not os.environ.get("CI")'),
    ("for item in items:\n"
     '    if config.getoption("--runslow"):\n'
     "        continue\n"
     '    item.add_marker(pytest.mark.skip(reason="slow"))',
     'not (config.getoption("--runslow"))'),
    # An `except` block's condition, as `collect_ignore` records it.
    ("try:\n    import redis\nexcept ImportError:\n    items[:] = []", 'find_spec("redis") is None'),
    # A `with` statement is an effect where it stands, and its body is read.
    ('if not os.environ.get("X"):\n    with open(os.devnull):\n        if not os.environ.get("Y"):\n'
     "            items[:] = []",
     '(not os.environ.get("X")) or (not os.environ.get("X") and not os.environ.get("Y"))'),
    ('with open(os.devnull):\n    if not os.environ.get("X"):\n        items[:] = []', None),
    # A `while` test is read.
    ('while not os.environ.get("X"):\n    items.pop()', 'not os.environ.get("X")'),
    # A call to a function the conftest defines is an effect where it is called.
    ('if not os.environ.get("NETWORK"):\n    _drop(items)', 'not os.environ.get("NETWORK")'),
    # pytest ignores what `pytest_collection_modifyitems` returns.
    ('if config.getoption("--keep"):\n    return True\nitems[:] = []', 'not (config.getoption("--keep"))'),
    # `session` is the environment too.
    ('if session.config.getoption("--all"):\n    return\nitems[:] = []', 'not (session.config.getoption("--all"))'),
])
def test_a_collection_hook_carries_the_condition_its_effects_fire_under(body, guard):
    params = "session, config, items" if "session" in body else "config, items"
    helper = "\ndef _drop(items):\n    items.clear()\n\n" if "_drop" in body else ""
    assert suite(helper + hook(body, params=params))[MODIFYITEMS] == guard


@pytest.mark.parametrize("body", [
    # #208's headline hook: the name it drops is a selector, not a guard.
    'items[:] = [item for item in items if item.name != "test_total"]',
    'for item in list(items):\n    if item.name == "test_total":\n        items.remove(item)',
    "items[:] = []",
    "if items:\n    items[:] = []",
    # A name bound to `items` is `items`.
    'selected = items\nif not os.environ.get("X"):\n    pass\nselected[:] = []',
    # One effect with no guard leaves the hook unguarded.
    'if not os.environ.get("NETWORK"):\n'
    '    items[:] = [i for i in items if "network" not in i.keywords]\n'
    "for item in items:\n"
    '    item.add_marker(pytest.mark.skip(reason="x"))',
    # A `match` case selects.
    'match os.environ.get("X"):\n    case "1":\n        items[:] = []',
    # A condition on a local the reading cannot follow.
    'run = os.environ.get("RUN")\nrun = True\nif not run:\n    items[:] = []',
])
def test_a_condition_that_selects_items_is_no_guard(body):
    assert suite(hook(body))[MODIFYITEMS] is None


@pytest.mark.parametrize("body, guard", [
    ('run_slow = config.getoption("--runslow")\nif run_slow:\n    return\nitems[:] = []',
     "not (config.getoption('--runslow'))"),
    ('a = os.environ.get("A")\nb = not a\nif b:\n    items[:] = []', "not os.environ.get('A')"),
    # The local's value is the guard: `True` holds everywhere.
    ("GATE = True\nif GATE:\n    items[:] = []", "True"),
])
def test_a_local_assigned_once_reads_as_its_value(body, guard):
    assert suite(hook(body))[MODIFYITEMS] == guard


def test_a_local_that_shadows_a_module_name_is_no_guard():
    source = HEAD + "GATE = False\n\n\ndef pytest_collection_modifyitems(config, items):\n" \
        "    GATE = True\n    if GATE:\n        items[:] = []\n"
    assert suite(source)[MODIFYITEMS] is None


@pytest.mark.parametrize("body, guard", [
    ("return True", None),
    ('return not os.environ.get("NETWORK") and collection_path.name == "test_network.py"',
     'not os.environ.get("NETWORK")'),
    ('if os.environ.get("NETWORK"):\n    return None\nreturn collection_path.name == "test_network.py"',
     'not (os.environ.get("NETWORK"))'),
    ("return False", None),
])
def test_an_ignore_collect_hook_acts_by_returning_true(body, guard):
    markers = suite(hook(body, name="pytest_ignore_collect", params="collection_path, config"))
    assert markers[IGNORE] == guard


def test_add_marker_skips_of_one_name_keep_the_weakest_guard():
    guarded = hook(NETWORK.replace("skip_network)", 'pytest.mark.skip(reason="x"))'))
    assert suite(guarded)[ADD_MARKER] == 'not os.environ.get("NETWORK")'
    both = guarded + "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='y'))\n"
    assert suite(both)[ADD_MARKER] is None
    outside = guarded + "\n\ndef pytest_runtest_setup(item):\n    item.add_marker(pytest.mark.skip(reason='z'))\n"
    assert suite(outside)[ADD_MARKER] is None


def test_weakest():
    assert weakest([]) is None
    assert weakest(["a", None]) is None
    assert weakest(["a", "a"]) == "a"
    assert weakest(["a", "b or c"]) == "(a) or (b or c)"


def test_collect_ignore_is_read_as_before():
    source = HEAD + 'collect_ignore = []\nif sys.version_info < (3, 9):\n    collect_ignore.append("test_legacy.py")\n'
    assert suite(source) == {"conftest.collect_ignore": "(sys.version_info < (3, 9))"}


# --- what D6 reads -------------------------------------------------------------

def analyze_change(*changes):
    ir, findings, verdict = analyze(
        list(changes), Config(), Contract(), [], datetime.date(2026, 10, 4),
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return ir, [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def unit_of(ir, path, qualname):
    file = next(f for f in ir.files if f.path == path)
    return file, next(u for u in file.units if u.qualname == qualname)


GATE = '@pytest.mark.skipif(sys.platform == "win32", reason="posix only")\n'
TEST_BASE = "import sys\n\nimport pytest\n\nfrom app.billing import total\n\n\n" + GATE + \
    "def test_total():\n    assert total() == 78.75\n"


def test_finding_marker_names_the_marker_a_finding_reports():
    after = TEST_BASE.replace(GATE, '@pytest.mark.skip(reason="flaky")\n@pytest.mark.xfail(reason="later")\n' + GATE)
    ir, found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", TEST_BASE.encode(), after.encode()))
    _file, unit = unit_of(ir, TEST_PATH, "test_total")
    assert sorted(finding_marker(f, unit) for f in found) == ["pytest.mark.skip", "pytest.mark.xfail"]
    # A suite-level control is keyed by its marker too.
    marks = hook('for item in items:\n    item.add_marker(pytest.mark.skip(reason="off"))')
    ir, found, _verdict = analyze_change(FileChange(CONFTEST, "modified", HEAD.encode(), marks.encode()))
    _file, unit = unit_of(ir, CONFTEST, "<suite>")
    assert sorted(finding_marker(f, unit) for f in found) == [ADD_MARKER, MODIFYITEMS]


def test_a_finding_with_no_marker_of_its_own_names_none():
    before = TEST_BASE.replace("def test_total():", "def test_total():\n    if sys.version_info < (3, 9):\n"
                               "        pytest.skip('old')", 1)
    after = before.replace("sys.version_info < (3, 9)", "sys.version_info >= (3, 0)")
    ir, found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", before.encode(), after.encode()))
    _file, unit = unit_of(ir, TEST_PATH, "test_total")
    assert [f.message for f in found] == [
        "test_total: skip guard now always fires ('sys.version_info >= (3, 0)')"
    ]
    assert finding_marker(found[0], unit) is None
    assert finding_marker(found[0], None) is None


@pytest.mark.parametrize("added, name, gate", [
    # #208 U1: the honest gate does not hold the skip beside it...
    ('@pytest.mark.skip(reason="flaky")\n', "pytest.mark.skip", False),
    # ...and #208 U5's gate holds its own finding.
    ('@pytest.mark.skipif(sys.version_info < (3, 12), reason="new")\n',
     "pytest.mark.skipif(sys.version_info<(3,12))", True),
])
def test_compat_gate_for_judges_the_findings_own_marker(added, name, gate):
    after = TEST_BASE.replace(GATE, added + GATE)
    ir, _found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", TEST_BASE.encode(), after.encode()))
    file, unit = unit_of(ir, TEST_PATH, "test_total")
    assert name in unit.delta.markers_added
    assert compat_gate_for(unit, file.constants, name) is gate
    assert compat_gate_for(unit, file.constants, None) is False


def test_every_marker_of_the_findings_name_must_qualify():
    # #208 U3: a guarded and an unguarded `pytest.skip` share the name.
    base = "import sys\n\nimport pytest\n\nfrom app.billing import total\n\n\n" \
        "def test_total():\n    if sys.platform == 'win32':\n        pytest.skip('posix only')\n" \
        "    assert total() == 78.75\n"
    after = base.replace("def test_total():\n", "def test_total():\n    pytest.skip('flaky')\n")
    ir, _found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", base.encode(), after.encode()))
    file, unit = unit_of(ir, TEST_PATH, "test_total")
    assert compat_gate_for(unit, file.constants, "pytest.skip") is False
    gated = base.replace("def test_total():\n", "def test_total():\n    if sys.platform == 'darwin':\n"
                         "        pytest.skip('not mac')\n")
    ir, _found, _verdict = analyze_change(FileChange(TEST_PATH, "modified", base.encode(), gated.encode()))
    file, unit = unit_of(ir, TEST_PATH, "test_total")
    assert compat_gate_for(unit, file.constants, "pytest.skip") is True




# --- an effect this reading cannot read still counts (ruling 209.Q2) ----------

@pytest.mark.parametrize("hidden", [
    # in the test of an `if`, or in a loop's iterable
    'if os.environ.get("X") or items.clear():\n    pass',
    "for _ in items.clear() or []:\n    pass",
    # through `session.items`, a bound method, or a name bound to the list
    "session.items.clear()",
    'getattr(items, "clear")()',
    "list(map(items.remove, list(items)))",
    "for _ in iter(items.pop, None):\n    pass",
    "sorted(list(items), key=items.remove)",
    "kept, = [items]\nkept.clear()",
    "kept = items\nkept *= 0",
    "del items[:]",
    "for items[0] in [None]:\n    pass",
    # returned, or in a nested definition's default or decorator
    "return items.clear()",
    "def _later(dropped=items.clear()):\n    pass",
    "@_drop\ndef _later():\n    pass",
    # a class body, which runs where it stands
    "class _Later:\n    items.clear()",
    # a `with` statement's context manager, which can swallow what ends its body
    "with _dropping(items):\n    pass",
    'if not os.environ.get("Y"):\n    with _quiet():\n        raise RuntimeError\nitems[:] = []',
])
def test_an_effect_this_reading_cannot_read_leaves_the_hook_unguarded(hidden):
    # Beside an honest guarded effect, each of these acts whatever NETWORK is.
    params = "session, config, items" if "session" in hidden else "config, items"
    assert suite(hook(NETWORK + "\n" + hidden, params=params))[MODIFYITEMS] is None


@pytest.mark.parametrize("body", [
    # A local rebound after its one assignment is not that assignment's value.
    "GATE = False\nfor GATE in [True]:\n    pass\nif GATE:\n    items[:] = []",
    "GATE = False\nif (GATE := True):\n    pass\nif GATE:\n    items[:] = []",
    # A rebound `config` is not pytest's.
    "config = FAKE\nif not config.getoption('--runslow'):\n    items[:] = []",
])
def test_a_rebound_name_is_no_guard(body):
    assert suite(hook(body))[MODIFYITEMS] is None


@pytest.mark.parametrize("prefix", [
    '"""Skip the network tests unless NETWORK is set."""',
    'log = logging.getLogger(__name__)\nlog.debug("collecting %d", len(items))',
    "import os",
    'marker = pytest.mark.skip(reason="offline")',
    'print("collected", len(items), sorted(i.name for i in items))',
    "order = sorted(items, key=lambda item: item.nodeid)",
])
def test_reads_beside_a_guarded_effect_keep_its_guard(prefix):
    source = "import logging\n" + hook(prefix + "\n" + NETWORK)
    assert suite(source)[MODIFYITEMS] == 'not os.environ.get("NETWORK")'


@pytest.mark.parametrize("module", [
    "def len(items):\n    items.clear()\n",
    "from helpers import *\n",
])
def test_a_builtin_the_conftest_may_rebind_is_not_a_read(module):
    source = module + hook('print(len(items))\n' + NETWORK)
    assert suite(source)[MODIFYITEMS] is None


# --- 209.Q4: unguarded means no guard that can be false ----------------------

@pytest.mark.parametrize("guard, constants, can_be_false", [
    (None, None, False),
    ("", None, False),
    ("True", None, False),
    ("sys.version_info >= (3, 0)", None, False),
    ("GATE", {"GATE": "True"}, False),
    ("GATE", {"GATE": "sys.platform == 'win32'"}, True),
    ("sys.platform == 'win32'", None, True),
    ('not os.environ.get("NETWORK")', None, True),
    ("not (config.getoption('--runslow'))", None, True),
    # An `except` block's condition that is not an expression still counts.
    ("except ValueError", None, True),
])
def test_guard_can_be_false(guard, constants, can_be_false):
    assert guard_can_be_false(guard, constants) is can_be_false


# --- a hook's guard edited to one that always holds ---------------------------

def test_a_hook_guard_edited_to_one_that_always_holds_is_reported():
    before = hook(NETWORK)
    after = before.replace('if not os.environ.get("NETWORK"):', "if sys.version_info >= (3, 0):")
    _ir, found, verdict = analyze_change(FileChange(CONFTEST, "modified", before.encode(), after.encode()))
    assert [(f.severity, f.message) for f in found] == [(
        "high",
        "<suite>: skip guard of the suite-level control now always fires "
        "('sys.version_info >= (3, 0)') (conftest.pytest_collection_modifyitems)",
    )]
    assert verdict == "block"


def test_a_hook_guard_rewritten_into_another_that_can_be_false_is_quiet():
    before = hook(NETWORK)
    after = before.replace('os.environ.get("NETWORK")', 'os.environ.get("NETWORK_TESTS")')
    _ir, found, verdict = analyze_change(FileChange(CONFTEST, "modified", before.encode(), after.encode()))
    assert found == [] and verdict == "pass"
