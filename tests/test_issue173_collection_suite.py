"""Issue #173: a collection change is resolved against the whole base suite.

The resolved-inventory proof (#90) read only byte-identical Python files, so a
test in a file the diff also edits did not exist for it. A marker selector
cannot be applied without editing the marked file: `@pytest.mark.slow` on the
only test plus a first `addopts = "-m 'not slow'"` fell back to the generic
warn and the verdict passed, while the same diff beside one untouched test
blocked. The controls pin the other direction: a tree that collected nothing
at base, and edits that only move, delete or relocate, stay at warn.
"""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


CARRIERS = ["pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"]
PRODUCTION = {"app/__init__.py": b"",
              "app/billing.py": b"def invoice_total(items):\n    return sum(i['price'] * i['qty'] for i in items)\n"}
BODY = (b"def test_invoice_total():\n"
        b"    items = [{'price': 10.0, 'qty': 3}, {'price': 5.0, 'qty': 9}]\n"
        b"    assert invoice_total(items) == 78.75\n")
TEST = b"from app.billing import invoice_total\n\n\n" + BODY
MARKED = b"import pytest\nfrom app.billing import invoice_total\n\n\n@pytest.mark.slow\n" + BODY
EDITED = b"# billing oracle\n" + TEST
OTHER = b"def test_padding():\n    assert True\n"
EXTRA = b"\n\ndef test_invoice_empty():\n    assert invoice_total([]) == 0\n"
SELECTOR = "-m 'not slow'"


def source(path, settings):
    section = "[tool.pytest.ini_options]" if path == "pyproject.toml" else "[tool:pytest]" if path == "setup.cfg" else "[pytest]"
    return (section + "\n" + "".join(f"{key} = {json.dumps(value) if path == 'pyproject.toml' else value}\n"
                                     for key, value in settings.items())).encode()


def judge(changes, snapshot):
    """CI_WORKFLOW_TOUCHED findings and the verdict over a complete head snapshot."""
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 1),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return [f for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"], verdict


def diff(before, after, untouched=None):
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path))
               for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    return judge(changes, {**PRODUCTION, **(untouched or {}), **after})


@pytest.mark.parametrize("carrier", CARRIERS)
def test_marker_deselecting_the_only_test_blocks(carrier):
    hits, verdict = diff({"tests/test_billing.py": TEST},
                         {"tests/test_billing.py": MARKED, carrier: source(carrier, {"addopts": SELECTOR})})
    assert [(f.path, f.severity) for f in hits] == [(carrier, "high")]
    assert "CI_TEST_COMMAND_WEAKENED" in hits[0].escalators
    assert hits[0].message.endswith("resolved pytest collection option introduced: -m not slow")
    assert verdict == "block"


@pytest.mark.parametrize("carrier", CARRIERS)
def test_emptied_collection_is_judged_like_partial_deselection(carrier):
    before = {"tests/test_billing.py": TEST}
    after = {"tests/test_billing.py": MARKED, carrier: source(carrier, {"addopts": SELECTOR})}
    partial, empty = diff(before, after, {"tests/test_padding.py": OTHER}), diff(before, after)
    assert [(f.severity, f.message) for f in empty[0]] == [(f.severity, f.message) for f in partial[0]]
    assert empty[1] == partial[1] == "block"


@pytest.mark.parametrize("carrier", CARRIERS)
def test_survivor_in_the_edited_file_does_not_hide_the_selector(carrier):
    hits, _ = diff({"tests/test_billing.py": TEST},
                   {"tests/test_billing.py": MARKED + EXTRA, carrier: source(carrier, {"addopts": SELECTOR})})
    assert [f.severity for f in hits] == ["high"]


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("option", [
    SELECTOR, '-m"not slow"', "-k 'not invoice'", "-k padding", "-kpadding",
    "--deselect tests/test_billing.py::test_invoice_total", "--deselect=tests/test_billing.py::test_invoice_total",
    "--ignore=tests/test_billing.py", "--ignore tests/test_billing.py", "--ignore-glob=tests/test_b*",
    "--co", "--collect-only", "-p no:python", "-pno:python",
    "-o python_files=check_*.py", "--override-ini=python_functions=check"])
def test_every_selector_spelling_resolves_against_an_edited_suite(carrier, option):
    hits, _ = diff({"tests/test_billing.py": TEST},
                   {"tests/test_billing.py": EDITED, carrier: source(carrier, {"addopts": option})})
    assert [f.severity for f in hits] == ["high"], option


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("settings,untouched", [
    ({"python_files": "check_*.py"}, {}),
    ({"python_functions": "check"}, {}),
    ({"norecursedirs": "tests"}, {}),
    ({"testpaths": "checks"}, {"checks/test_check.py": OTHER}),
])
def test_settings_excluding_an_edited_test_block(carrier, settings, untouched):
    hits, _ = diff({"tests/test_billing.py": TEST},
                   {"tests/test_billing.py": EDITED, carrier: source(carrier, settings)}, untouched)
    assert [f.severity for f in hits] == ["high"]
    assert hits[0].message.endswith("excludes 1 existing test(s), including tests/test_billing.py::test_invoice_total")


def test_renamed_marked_test_keeps_its_base_identity():
    config = source("pyproject.toml", {"addopts": SELECTOR})
    changes = [FileChange("pyproject.toml", "added", None, config),
               FileChange("tests/test_billing_slow.py", "modified", TEST, MARKED, old_path="tests/test_billing.py")]
    hits, verdict = judge(changes, {**PRODUCTION, "pyproject.toml": config, "tests/test_billing_slow.py": MARKED})
    assert [f.severity for f in hits] == ["high"]
    assert verdict == "block"


def test_rename_into_a_newly_excluded_directory_is_a_settings_effect():
    config = source("pytest.ini", {"norecursedirs": "slow"})
    changes = [FileChange("pytest.ini", "added", None, config),
               FileChange("tests/slow/test_billing.py", "modified", TEST, TEST, old_path="tests/test_billing.py")]
    hits, _ = judge(changes, {**PRODUCTION, "pytest.ini": config, "tests/slow/test_billing.py": TEST})
    assert [f.severity for f in hits] == ["high"]
    assert hits[0].message.endswith("including tests/test_billing.py::test_invoice_total")


# Controls: the same shapes that must not block.

@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("base", [{}, {"tests/test_billing.py": b"from app.billing import invoice_total\n"}],
                         ids=["first-test", "placeholder-module"])
def test_selector_over_a_base_that_collected_nothing_stays_warn(carrier, base):
    hits, _ = diff(base, {"tests/test_billing.py": MARKED, carrier: source(carrier, {"addopts": SELECTOR})})
    assert [f.severity for f in hits] == ["warn"]


@pytest.mark.parametrize("carrier", CARRIERS)
def test_first_configuration_without_a_selector_beside_an_edited_test_stays_warn(carrier):
    hits, _ = diff({"tests/test_billing.py": TEST},
                   {"tests/test_billing.py": TEST + EXTRA,
                    carrier: source(carrier, {"testpaths": "tests", "addopts": "-ra"})})
    assert [f.severity for f in hits] == ["warn"]


@pytest.mark.parametrize("carrier", CARRIERS)
def test_moving_or_deleting_a_test_is_not_a_settings_effect(carrier):
    moved, _ = diff({"tests/test_billing.py": TEST},
                    {"tests/test_billing.py": b"# moved to tests/unit/test_billing.py\n",
                     "tests/unit/test_billing.py": TEST, carrier: source(carrier, {"testpaths": "tests/unit"})})
    deleted, _ = diff({"tests/test_billing.py": TEST}, {carrier: source(carrier, {"python_files": "check_*.py"})})
    assert [f.severity for f in moved] == [f.severity for f in deleted] == ["warn"]


def test_selector_relocated_beside_an_edited_test_stays_warn():
    hits, _ = diff({"setup.cfg": source("setup.cfg", {"addopts": SELECTOR}), "tests/test_billing.py": MARKED},
                   {"pyproject.toml": source("pyproject.toml", {"addopts": SELECTOR}),
                    "tests/test_billing.py": MARKED + EXTRA})
    assert hits and all(f.severity == "warn" for f in hits)


def test_rename_beside_a_broadening_setting_stays_warn():
    config = source("pytest.ini", {"python_files": "test_*.py check_*.py"})
    changes = [FileChange("pytest.ini", "added", None, config),
               FileChange("tests/unit/test_billing.py", "modified", TEST, TEST, old_path="tests/test_billing.py")]
    hits, _ = judge(changes, {**PRODUCTION, "pytest.ini": config, "tests/unit/test_billing.py": TEST})
    assert [f.severity for f in hits] == ["warn"]
