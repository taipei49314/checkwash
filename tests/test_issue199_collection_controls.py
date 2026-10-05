"""Issue #199: a conftest runtime control does not withhold the collection inventory.

The resolved collection inventory (#173) withheld its proof whenever a head
conftest carried any marker. v0.5.0 mints one for every conftest fixture whose
setup always ends in skip or xfail, so one such fixture anywhere in the tree,
requested or not, turned a narrowing that only the inventory reports from
block into warn (#199 M1-M8). Ruling 199.Q1: only the collection controls of
SPEC §2b withhold, with `pytest_plugins` and a conftest that does not parse.
A runtime control does not, whether it is a fixture or an execution or report
hook (#199 H1, R1): the test is still collected, and the skip is reported
where it is planted.

The acceptance matrix is the issue's: fixture spelling x autouse x placement x
request x narrowing. Every cell must judge the narrowing exactly as the same
tree without the conftest does.
"""
import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.conftest_controls import (
    COLLECTION,
    FIXTURE_SETUP,
    RUNTIME,
    SKIP_MARK,
    marker_kind,
)
from checkwash.frontends.python.frontend import parse_python
from checkwash.gitio.snapshot import search_source_mapping

APP = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
TEST_BILLING = (b"import pytest\n\nfrom app.billing import total\n\n\n"
                b"@pytest.mark.slow\ndef test_total():\n    assert total() == 78.75\n")
TEST_NET = b"def test_fetch(needs_network):\n    assert needs_network == 1\n"

SPELLINGS = {
    "skip": b'    pytest.skip("network tests are disabled")\n',
    "xfail": b'    pytest.xfail("network tests are disabled")\n',
    "skip_exception": b'    raise pytest.skip.Exception("network tests are disabled")\n',
    "unittest_skiptest": b'    raise unittest.SkipTest("network tests are disabled")\n',
}

# (conftest path, path of the test that requests the fixture). A directory
# that holds no tests is also outside `testpaths = tests` in R4.
PLACEMENTS = {
    "tests": ("tests/conftest.py", "tests/test_net.py"),
    "nested": ("tests/sub/conftest.py", "tests/sub/test_net.py"),
    "root": ("conftest.py", "tests/test_net.py"),
    "no_tests_dir": ("tools/legacy/conftest.py", "tests/test_net.py"),
}

MARKED = b'addopts = -m "not slow"\nmarkers =\n    slow: slow tests\n'
# (base pytest.ini or None, head pytest.ini). V1-V3 and R2-R4 are the issue's.
NARROWINGS = {
    "V1_first_python_files": (None, b"[pytest]\npython_files = smoke_*.py\n"),
    "V2_changed_python_files": (b"[pytest]\npython_files = test_*.py\n", b"[pytest]\npython_files = smoke_*.py\n"),
    "V3_first_marker_selector": (None, b"[pytest]\n" + MARKED),
    "first_keyword_selector": (None, b"[pytest]\naddopts = -k smoke\n"),
    "first_testpaths": (None, b"[pytest]\ntestpaths = smoke\n"),
    "R2_existing_gains_selector": (b"[pytest]\npython_files = test_*.py\n",
                                   b"[pytest]\npython_files = test_*.py\n" + MARKED),
    "R3_existing_gains_testpaths": (b"[pytest]\npython_files = test_*.py\n",
                                    b"[pytest]\npython_files = test_*.py\ntestpaths = smoke\n"),
    "R4_outside_testpaths": (b"[pytest]\ntestpaths = tests\n",
                             b"[pytest]\ntestpaths = tests\npython_files = smoke_*.py\n"),
}


def fixture(spelling, autouse):
    decorator = b"@pytest.fixture(autouse=True)\n" if autouse else b"@pytest.fixture\n"
    return b"import unittest\n\nimport pytest\n\n\n" + decorator + b"def needs_network():\n" + SPELLINGS[spelling]


def kinds(source):
    parsed = parse_python(source, collect_tests=False, conftest=True)
    return {marker_kind(m.name) for u in parsed.units for m in u.side.markers}


def judge(tree, narrowing):
    """(findings, verdict) for a narrowing applied to a complete in-memory tree."""
    base, head_ini = NARROWINGS[narrowing]
    before = dict(tree, **({"pytest.ini": base} if base is not None else {}))
    head = dict(before, **{"pytest.ini": head_ini})
    changes = [FileChange("pytest.ini", "modified" if base is not None else "added", base, head_ini)]
    searcher = functools.partial(search_source_mapping, head)
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 3),
        head_reader=head.get, head_searcher=searcher, root_reader=head.get, root_searcher=searcher,
        root_path_lister=lambda: sorted(head), root_batch_reader=lambda paths: {p: head.get(p) for p in paths})
    return tuple(sorted((f.rule, f.path, f.severity, f.message) for f in findings)), verdict


def tree(requester=None, **extra):
    return {**APP, "tests/test_billing.py": TEST_BILLING, **({requester: TEST_NET} if requester else {}), **extra}


@functools.lru_cache(maxsize=None)
def without_conftest(requester, narrowing):
    return judge(tree(requester), narrowing)


@pytest.mark.parametrize("narrowing", sorted(NARROWINGS))
@pytest.mark.parametrize("requested", [False, True], ids=["unrequested", "requested"])
@pytest.mark.parametrize("placement", sorted(PLACEMENTS))
@pytest.mark.parametrize("autouse", [False, True], ids=["plain", "autouse"])
@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_a_skipping_conftest_fixture_never_withholds_the_inventory(spelling, autouse, placement, requested, narrowing):
    conftest, requester = PLACEMENTS[placement]
    source = fixture(spelling, autouse)
    assert FIXTURE_SETUP in kinds(source)
    requester = requester if requested else None
    assert judge(tree(requester, **{conftest: source}), narrowing) == without_conftest(requester, narrowing)


@pytest.mark.parametrize("narrowing", ["V1_first_python_files", "V2_changed_python_files", "V3_first_marker_selector"])
@pytest.mark.parametrize("spelling,autouse", [("skip", False), ("xfail", False), ("unittest_skiptest", False),
                                              ("skip", True)], ids=["M1-3", "M4", "M5", "M8"])
def test_issue_rows_block(spelling, autouse, narrowing):
    findings, verdict = judge(tree(**{"tests/conftest.py": fixture(spelling, autouse)}), narrowing)
    assert [(rule, path, severity) for rule, path, severity, _ in findings] == [
        ("CI_WORKFLOW_TOUCHED", "pytest.ini", "high")]
    assert verdict == "block"


RUNTIME_HOOKS = {
    "H1_runtest_setup_skip": b'import pytest\n\n\ndef pytest_runtest_setup(item):\n    pytest.skip("suite disabled")\n',
    "R1_makereport_passed": (b"import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n"
                             b"def pytest_runtest_makereport(item, call):\n    outcome = yield\n"
                             b'    report = outcome.get_result()\n    report.outcome = "passed"\n'),
}


@pytest.mark.parametrize("narrowing", ["V1_first_python_files", "V2_changed_python_files", "V3_first_marker_selector"])
@pytest.mark.parametrize("hook", sorted(RUNTIME_HOOKS))
def test_runtime_hooks_no_longer_withhold(hook, narrowing):
    """#199 H1 and R1 withheld the inventory in v0.4.2 and v0.5.0; 199.Q1 ends that."""
    assert RUNTIME in kinds(RUNTIME_HOOKS[hook])
    result = judge(tree(**{"tests/conftest.py": RUNTIME_HOOKS[hook]}), narrowing)
    assert result == without_conftest(None, narrowing)
    assert result[1] == "block"


COLLECTION_CONTROLS = {
    "collect_ignore": b'collect_ignore = ["test_legacy.py"]\n',
    "collect_ignore_glob": b'collect_ignore_glob = ["legacy_*.py"]\n',
    "pytest_ignore_collect": (b"def pytest_ignore_collect(collection_path, config):\n"
                              b'    return collection_path.name == "test_legacy.py"\n'),
    "pytest_collection_modifyitems": b"def pytest_collection_modifyitems(config, items):\n    items[:] = items[:1]\n",
    "add_marker_skip": b"import pytest\n\n\ndef pytest_itemcollected(item):\n    item.add_marker(pytest.mark.skip)\n",
}


@pytest.mark.parametrize("control", sorted(COLLECTION_CONTROLS))
def test_collection_controls_still_withhold(control):
    """#199 K1: a control that changes what pytest collects still withholds."""
    assert kinds(COLLECTION_CONTROLS[control]) & {COLLECTION, SKIP_MARK}
    findings, verdict = judge(tree(**{"tests/conftest.py": COLLECTION_CONTROLS[control]}), "V1_first_python_files")
    assert [(rule, severity) for rule, _, severity, _ in findings] == [("CI_WORKFLOW_TOUCHED", "warn")]
    assert verdict == "pass"


# Disables nothing, so withholds nothing: pytest never reads a conftest's
# `pytestmark` (#209 Q3), and a hook with no effect that can drop or disable an
# item is not a control (#209 Q2).
DISABLES_NOTHING = {
    "pytestmark": b"import pytest\n\npytestmark = pytest.mark.skip\n",
    "ignore_collect_returns_false": b"def pytest_ignore_collect(collection_path, config):\n    return False\n",
    "sort_only_hook": b"def pytest_collection_modifyitems(config, items):\n    items.sort(key=lambda item: item.nodeid)\n",
    "labelling_hook": (b"import pytest\n\n\ndef pytest_collection_modifyitems(config, items):\n"
                       b"    for item in items:\n        item.add_marker(pytest.mark.timeout(30))\n"),
}


@pytest.mark.parametrize("narrowing", ["V1_first_python_files", "V2_changed_python_files", "V3_first_marker_selector"])
@pytest.mark.parametrize("control", sorted(DISABLES_NOTHING))
def test_what_disables_nothing_never_withholds(control, narrowing):
    result = judge(tree(**{"tests/conftest.py": DISABLES_NOTHING[control]}), narrowing)
    assert result == without_conftest(None, narrowing)
    assert result[1] == "block"


@pytest.mark.parametrize("source", [b'pytest_plugins = ["myplugin"]\n', b"def broken(:\n"],
                         ids=["pytest_plugins", "unparsable"])
def test_plugins_and_parse_failure_still_withhold(source):
    findings, verdict = judge(tree(**{"tests/conftest.py": source}), "V1_first_python_files")
    assert [(rule, severity) for rule, _, severity, _ in findings] == [("CI_WORKFLOW_TOUCHED", "warn")]
    assert verdict == "pass"
