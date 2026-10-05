"""A guard removed from an existing suite-level control is reported (#261).

A suite-level control is `collect_ignore`, `collect_ignore_glob`, either
collection hook, or an `add_marker` skip in one. A diff that took the guard
off one that already existed reported nothing: the control keeps its marker,
so none is added, and the head side has no guard left for `guards_weakened`
to evaluate. For `collect_ignore`, the ignored paths stay the same too, so no
path is added either (row 81). Editing the guard to one that always holds was
reported; removing it outright was not.

261.Q1: when the guard could be false at base and there is none at head,
TEST_DISABLED reports "skip guard removed of the suite-level control (was
'<guard>') (<marker>)", with the guard family's identity, judged as an
unguarded control: no COMPAT_GATE and no repair evidence.

261.Q2: an unguarded effect added beside guarded ones is the same event.

261.Q3: a constant `True` the hook reading drops is a removed guard.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint

CONFTEST = "tests/conftest.py"
HEAD = "import importlib.util\nimport os\nimport sys\n\nimport pytest\n"
ENV = 'not os.environ.get("NETWORK")'
BILLING = b"def total():\n    return 78.75\n"
MODIFYITEMS = "conftest.pytest_collection_modifyitems"
IGNORE = "conftest.pytest_ignore_collect"
ADD_MARKER = "conftest.add_marker_skip"
COLLECT_IGNORE = "conftest.collect_ignore"


def analyze_change(before, after, *others):
    _ir, findings, verdict = analyze(
        [FileChange(CONFTEST, "modified", before.encode(), after.encode()), *others],
        Config(), Contract(), [], datetime.date(2026, 10, 5),
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def removed(was, name):
    return f"<suite>: skip guard removed of the suite-level control (was {was!r}) ({name})"


def collect_ignore(guard, name="collect_ignore", path="test_network.py"):
    line = f'{name}.append("{path}")'
    if guard is None:
        return HEAD + f"\n{name} = []\n{line}\n"
    return HEAD + f"\n{name} = []\nif {guard}:\n    {line}\n"


def modifyitems(guard, mark="skip_network", extra=""):
    body = (
        "for item in items:\n"
        '    if "network" in item.keywords:\n'
        f"        item.add_marker({mark})\n"
    )
    if mark == "skip_network":
        body = 'skip_network = pytest.mark.skip(reason="set NETWORK=1 to run")\n' + body
    if guard is not None:
        body = f"if {guard}:\n" + "".join(f"    {line}\n" for line in body.splitlines())
    lines = "".join(f"    {line}\n" for line in (body + extra).splitlines())
    return HEAD + f"\n\ndef pytest_collection_modifyitems(config, items):\n{lines}"


def ignore_collect(guard):
    body = 'return collection_path.name == "test_network.py"'
    if guard is not None:
        body = f"if {guard}:\n    {body}"
    lines = "".join(f"    {line}\n" for line in body.splitlines())
    return HEAD + f"\n\ndef pytest_ignore_collect(collection_path, config):\n{lines}"


DIRECT = 'pytest.mark.skip(reason="set NETWORK=1 to run")'
DROP = 'items[:] = [item for item in items if "billing" not in item.nodeid]\n'
IMPORT_GATE = HEAD + '\ncollect_ignore = []\ntry:\n    import redis\nexcept ImportError:\n    collect_ignore.append("test_network.py")\n'
EARLY_RETURN = (
    HEAD + "\n\ndef pytest_collection_modifyitems(config, items):\n"
    '    if os.environ.get("NETWORK"):\n        return\n'
    '    items[:] = [item for item in items if "network" not in item.keywords]\n'
)


# --- 261.Q1: every suite-level control, every way its guard goes ----------------

@pytest.mark.parametrize("before, after, expected", [
    # G1, and its glob and optional-dependency spellings
    (collect_ignore(ENV), collect_ignore(None), [(f"({ENV})", COLLECT_IGNORE)]),
    (collect_ignore(ENV, "collect_ignore_glob", "test_net*.py"),
     collect_ignore(None, "collect_ignore_glob", "test_net*.py"), [(f"({ENV})", COLLECT_IGNORE)]),
    (IMPORT_GATE, collect_ignore(None), [('(find_spec("redis") is None)', COLLECT_IGNORE)]),
    # G2, and the other hook
    (modifyitems(ENV), modifyitems(None), [(ENV, MODIFYITEMS)]),
    (ignore_collect('not config.getoption("--network")'), ignore_collect(None),
     [('not config.getoption("--network")', IGNORE)]),
    # an early return is the guard of what follows it
    (EARLY_RETURN, EARLY_RETURN.replace('    if os.environ.get("NETWORK"):\n        return\n', ""),
     [('not (os.environ.get("NETWORK"))', MODIFYITEMS)]),
    # an `add_marker` skip in a hook is a control of its own
    (modifyitems(ENV, DIRECT), modifyitems(None, DIRECT), [(ENV, MODIFYITEMS), (ENV, ADD_MARKER)]),
], ids=["G1", "G1-glob", "G1-import-gate", "G2", "ignore-collect", "early-return", "add-marker"])
def test_a_removed_guard_is_reported_for_every_suite_level_control(before, after, expected):
    found, verdict = analyze_change(before, after)
    assert [(f.message, f.severity, f.shape, f.escalators) for f in found] == [
        (removed(was, name), "high", "guard_weakened", ["NO_PROD_CHANGE_IN_DIFF"]) for was, name in expected
    ]
    assert [f.fingerprint for f in found] == [
        make_fingerprint("TEST_DISABLED", CONFTEST, "<suite>", f"guard:{name}") for _was, name in expected
    ]
    assert all(f.after is not None for f in found)
    assert verdict == "block"


# --- 261.Q2: an unguarded effect beside guarded ones -----------------------------

@pytest.mark.parametrize("before, after, expected", [
    # G3: the hook keeps its guarded loop and gains an unguarded drop
    (modifyitems(ENV), modifyitems(ENV, extra=DROP), (ENV, MODIFYITEMS)),
    # the same path ignored again, unguarded, beside the guarded statement
    (collect_ignore(ENV), collect_ignore(ENV) + 'collect_ignore.append("test_network.py")\n',
     (f"({ENV})", COLLECT_IGNORE)),
], ids=["G3", "collect-ignore"])
def test_an_unguarded_effect_beside_guarded_ones_is_the_same_event(before, after, expected):
    found, verdict = analyze_change(before, after)
    assert [(f.message, f.severity) for f in found] == [(removed(*expected), "high")]
    assert verdict == "block"


# --- 261.Q3: a constant the reading drops ----------------------------------------

def test_a_guard_edited_to_a_constant_true_reads_as_removed():
    # G4: the hook reading drops a constant `True`, so the hook has no guard.
    found, verdict = analyze_change(modifyitems(ENV), modifyitems("True"))
    assert [(f.message, f.severity) for f in found] == [(removed(ENV, MODIFYITEMS), "high")]
    assert verdict == "block"


# --- judged as an unguarded control: no COMPAT_GATE, no repair evidence ---------

def test_a_platform_guard_removed_earns_no_compat_gate():
    found, verdict = analyze_change(modifyitems('sys.platform == "win32"'), modifyitems(None))
    assert [(f.severity, f.deescalators) for f in found] == [("high", [])]
    assert verdict == "block"


@pytest.mark.parametrize("before, after", [
    (modifyitems(ENV), modifyitems(None)),
    (collect_ignore(ENV), collect_ignore(None)),
], ids=["hook", "collect-ignore"])
def test_a_removed_guard_earns_no_repair_evidence(before, after):
    prod = FileChange("app/billing.py", "modified", BILLING, b"def total():\n    return 78.76\n")
    found, verdict = analyze_change(before, after, prod)
    assert [(f.severity, f.escalators, f.deescalators) for f in found] == [
        ("high", ["COLLECTION_CONTROL_UNEXPLAINED"], [])]
    assert verdict == "block"


# --- the head guard is #209's reading ---------------------------------------------

OUTSIDE = (
    HEAD + f"\n\nif {ENV}:\n\n    def pytest_collection_modifyitems(config, items):\n"
    '        for item in items:\n            if "network" in item.keywords:\n'
    f"                item.add_marker({DIRECT})\n"
)
HELPER = (
    HEAD + f"\n\ndef _offline():\n    return {ENV}\n\n\n"
    "def pytest_collection_modifyitems(config, items):\n    if _offline():\n"
    '        for item in items:\n            if "network" in item.keywords:\n'
    f"                item.add_marker({DIRECT})\n"
)


@pytest.mark.parametrize("after, names", [
    (OUTSIDE, [MODIFYITEMS, ADD_MARKER]),
    # the `add_marker` call keeps `_offline()` as its guard: a module-level
    # name may guard it; the hook evaluating that call is an effect
    (HELPER, [MODIFYITEMS]),
], ids=["module-level-if", "conftest-helper"])
def test_a_guard_moved_where_the_hook_reading_does_not_look_reads_as_removed(after, names):
    # A hook defined under a module-level `if` carries no guard from it, and
    # a call to a function the conftest defines is an effect (209.Q2): the
    # same hook added in either form already blocks.
    found, verdict = analyze_change(modifyitems(ENV, DIRECT), after)
    assert [f.message for f in found] == [removed(ENV, name) for name in names]
    assert verdict == "block"


# --- what is no event ----------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    # a base guard that always held guarded nothing
    (modifyitems("sys.version_info >= (3, 0)"), modifyitems(None)),
    (collect_ignore("True"), collect_ignore(None)),
    # nothing was guarded at base
    (modifyitems(None), modifyitems(None, extra=DROP)),
    # a guard rewritten into another that can be false
    (modifyitems(ENV), modifyitems('os.environ.get("NETWORK") is None')),
    (collect_ignore(ENV), collect_ignore('os.environ.get("NETWORK") is None')),
    # the control is gone
    (modifyitems(ENV), HEAD),
    # an `if` folded into what `pytest_ignore_collect` returns keeps its guard
    (ignore_collect('not config.getoption("--network")'),
     HEAD + '\n\ndef pytest_ignore_collect(collection_path, config):\n'
     '    return not config.getoption("--network") and collection_path.name == "test_network.py"\n'),
], ids=["always-true-hook", "always-true-collect-ignore", "never-guarded", "hook-guard-rewritten",
        "collect-ignore-guard-rewritten", "control-gone", "ignore-collect-folded"])
def test_what_is_no_event(before, after):
    assert analyze_change(before, after) == ([], "pass")


# --- what was already reported keeps its wording and its identity --------------

def test_a_guard_that_now_always_fires_keeps_its_message():
    # G5 and G6: the contrast rows of #261.
    always = "sys.version_info >= (3, 0)"
    found, _verdict = analyze_change(modifyitems(ENV), modifyitems(always))
    assert [f.message for f in found] == [
        f"<suite>: skip guard of the suite-level control now always fires ({always!r}) ({MODIFYITEMS})"]
    found, _verdict = analyze_change(collect_ignore(ENV), collect_ignore(always))
    assert [f.message for f in found] == [f"<suite>: skip guard now always fires ('({always})')"]


def test_a_removed_guard_shares_the_identity_of_one_that_always_fires():
    # One fingerprint for the guard family, so an exemption recorded for one
    # edit covers the other.
    gone, _ = analyze_change(modifyitems(ENV), modifyitems(None))
    always, _ = analyze_change(modifyitems(ENV), modifyitems("sys.version_info >= (3, 0)"))
    assert [f.fingerprint for f in gone] == [f.fingerprint for f in always]


def test_a_removed_guard_and_a_path_gained_are_one_event():
    # Row 81 reports a path added to an unguarded control; the removed guard
    # is already that event, and reporting it twice would be noise.
    after = collect_ignore(None) + 'collect_ignore.append("test_billing.py")\n'
    found, verdict = analyze_change(collect_ignore(ENV), after)
    assert [(f.message, f.severity) for f in found] == [(removed(f"({ENV})", COLLECT_IGNORE), "high")]
    assert verdict == "block"


def test_a_path_gained_by_an_unguarded_control_is_still_row_81():
    after = collect_ignore(None) + 'collect_ignore.append("test_billing.py")\n'
    found, verdict = analyze_change(collect_ignore(None), after)
    assert [(f.severity, f.shape, f.fingerprint) for f in found] == [(
        "high", "guard_weakened", make_fingerprint("TEST_DISABLED", CONFTEST, "<suite>", f"guard:{COLLECT_IGNORE}"),
    )]
    assert "removed" not in found[0].message
    assert verdict == "block"
