"""One classification of the marker names the Python frontend mints (#199 Q4).

Two readers branch on what a marker is. The resolved collection inventory
(`collection_inventory.py`) withholds its proof when a conftest changes what
pytest collects, and TEST_DISABLED says what kind of control a diff added.
Both read this module, so each marker family is classified once, here.

A name this module does not know has no kind. It is not a collection control,
and TEST_DISABLED describes it as a plain disabling marker. A new family
therefore joins no reader by default, and `tests/test_conftest_controls.py`
fails until it is classified here.
"""
from __future__ import annotations

from checkwash.frontends.python.frontend import _SKIP_DECORATORS
from checkwash.frontends.python.setup_skip_controls import BODY_MARKERS

# A conftest control that changes what pytest collects (SPEC §2b).
COLLECTION = "collection"
# A conftest execution or report hook (`pytest_runtest_setup` that always
# skips, a `pytest_runtest_makereport` that rewrites the outcome, ...): the
# test is collected, then skipped or reported as something else.
RUNTIME = "runtime"
# A conftest fixture whose setup always ends in skip or xfail. A runtime
# control too, but it fires only for the tests that request it.
FIXTURE_SETUP = "fixture_setup"
# Skip or xfail in the setup a test runs: a fixture it reaches, in its module or
# in a conftest above it (#223), or xunit setup.
SETUP = "setup"
# A whole module disabled: `__test__ = False`, or a module-level `pytest.skip`,
# `pytest.xfail` or `pytest.importorskip`.
MODULE = "module"
# A skip or xfail mark: a decorator, or a `pytestmark` assignment.
SKIP_MARK = "skip_mark"
# A skip or xfail called in the test body.
SKIP_CALL = "skip_call"

# `_conftest_unit` mints these names, and only these, for collection controls.
COLLECTION_NAMES = frozenset({
    "conftest.collect_ignore",
    "conftest.pytest_ignore_collect",
    "conftest.pytest_collection_modifyitems",
    "conftest.add_marker_skip",
})

# The kinds minted on a conftest's `<suite>` unit, runtime ones included.
# TEST_DISABLED gives all of them the `collection_control` shape. Relabelling
# the runtime ones would change what the findings JSON means, and needs its
# own DECISIONS entry (#199 Q4).
SUITE_KINDS = frozenset({COLLECTION, RUNTIME, FIXTURE_SETUP})


def marker_kind(name: str) -> str | None:
    """The family this marker name belongs to, or None for one this module does not know."""
    if name in COLLECTION_NAMES:
        return COLLECTION
    if name.startswith("conftest.runtime.fixture."):
        return FIXTURE_SETUP
    if name.startswith("conftest.runtime."):
        return RUNTIME
    if name.startswith("setup."):
        return SETUP
    if name.startswith("module."):
        return MODULE
    if name in BODY_MARKERS:
        return SKIP_CALL
    # `_marker_identity` appends a mark's condition: `pytest.mark.skipif(cond)`.
    if name.split("(", 1)[0] in _SKIP_DECORATORS:
        return SKIP_MARK
    return None


def is_collection_control(name: str) -> bool:
    """Does this marker on a conftest's `<suite>` unit change what pytest collects?

    The SPEC §2b list: `collect_ignore`/`collect_ignore_glob`, the
    `pytest_ignore_collect` and `pytest_collection_modifyitems` hooks, and an
    `add_marker(...skip)` call. A runtime control is not one: the test is
    still collected, and the skip is reported where it is planted (#199 Q1,
    Q2). Nor is a `pytestmark` mark, the only skip mark that unit carries:
    pytest does not read `pytestmark` from conftest.py, which it does not
    collect as a test module, so the mark disables nothing (#209 Q3).
    """
    return marker_kind(name) == COLLECTION
