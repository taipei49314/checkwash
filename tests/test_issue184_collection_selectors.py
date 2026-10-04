"""#196 184.1 and 184.2: which runs a new pytest selector reaches, and what it can leave out.

184.1: explicit CLI targets (`pytest tests`) override testpaths, so the
resolved inventory withheld its whole proof from a repository whose CI passes
targets, and a first `addopts = "-m 'not slow'"` there passed. pytest still
prepends the root config's addopts to a targeted run: a new selector is now
judged against the base-suite tests beneath the targets, when discovery from
the targets finds the same root config on both sides. The settings proof
stays withheld for a targeted run.

184.2: a first config's option that leaves no test out (`-p no:cacheprovider`,
`--ignore=docs` with no tests in docs) blocked as a new selector. A path
option now counts only when it drops a base-suite test, and `-p no:` only for
a plugin outside a short list whose absence changes no outcome. Markers,
keywords, `--co`, `no:python`, `no:unittest` and unknown plugins keep
blocking.
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
TEST = (b"import pytest\nfrom app.billing import invoice_total\n\n\n@pytest.mark.slow\n"
        b"def test_invoice_total():\n    assert invoice_total([]) == 0\n")
SELECTOR = "-m 'not slow'"


def source(path, settings):
    section = "[tool.pytest.ini_options]" if path == "pyproject.toml" else "[tool:pytest]" if path == "setup.cfg" else "[pytest]"
    return (section + "\n" + "".join(f"{key} = {json.dumps(value) if path == 'pyproject.toml' else value}\n"
                                     for key, value in settings.items())).encode()


def workflow(command):
    return ("name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
            f"    steps:\n      - run: {command}\n").encode()


def judge(before, after, untouched=None):
    """CI_WORKFLOW_TOUCHED (severity, message) pairs and the verdict over a complete head snapshot."""
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path))
               for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    snapshot = {**PRODUCTION, "tests/test_billing.py": TEST, **(untouched or {}), **after}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 4),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return [(f.severity, f.message) for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"], verdict


# --- 184.1: a targeted run inherits the root config's addopts ----------------------------

@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("command", ["pytest tests", "python -m pytest tests/test_billing.py", "pytest tests -q"])
def test_a_first_selector_reaches_a_targeted_run(carrier, command):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": SELECTOR})},
                          {".github/workflows/ci.yml": workflow(command)})
    assert hits == [("high", "CI configuration changed; test command weakened: "
                             "resolved pytest collection option introduced: -m not slow")]
    assert verdict == "block"


def test_a_targeted_run_with_no_base_test_beneath_its_targets_is_not_reached():
    hits, verdict = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})},
                          {".github/workflows/ci.yml": workflow("pytest integration")})
    assert [severity for severity, _ in hits] == ["warn"]
    assert verdict == "pass"


def test_a_nested_config_governing_the_targets_withholds_the_proof():
    # Discovery from `tests` finds tests/pytest.ini, so the root addopts never
    # reach that run.
    nested = {".github/workflows/ci.yml": workflow("pytest tests"), "tests/pytest.ini": b"[pytest]\n"}
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})}, nested)
    assert [severity for severity, _ in hits] == ["warn"]


def test_a_nested_config_the_diff_deletes_withholds_the_proof():
    # The same root config must govern the targeted run on both sides; at base
    # tests/pytest.ini did.
    runners = {".github/workflows/ci.yml": workflow("pytest tests")}
    hits, _ = judge({"tests/pytest.ini": b"[pytest]\n"}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})},
                    runners)
    assert [severity for severity, _ in hits] == ["warn"]


def test_a_targetless_run_beside_a_targeted_one_is_reached():
    runners = {".github/workflows/ci.yml": workflow("pytest integration"), "scripts/test.sh": b"#!/bin/sh\npytest\n"}
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})}, runners)
    assert [severity for severity, _ in hits] == ["high"]


@pytest.mark.parametrize("settings", [{"python_files": "check_*.py"}, {"testpaths": "checks"}])
def test_the_settings_proof_stays_withheld_for_a_targeted_run(settings):
    # Explicit targets override testpaths, and pytest applies python_files
    # only to the files it walks into, not to a file named as a target.
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", settings)},
                    {".github/workflows/ci.yml": workflow("pytest tests")})
    assert [severity for severity, _ in hits] == ["warn"]


# --- 184.2: a path option or a plugin counts by what it can leave out ---------------------

@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("option", [
    "-p no:cacheprovider", "-pno:cacheprovider", "-p no:faulthandler", "-p no:pastebin", "-p no:stepwise",
    "--ignore=docs", "--ignore docs", "--ignore=tests/test_other.py", "--ignore-glob=docs/*",
    "--ignore-glob=*_slow.py", "--deselect tests/test_billing.py::test_other",
    "--deselect=tests/test_other.py",
])
def test_a_first_option_that_leaves_no_test_out_stays_warn(carrier, option):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": option})}, {"docs/conf.py": b"x = 1\n"})
    assert [severity for severity, _ in hits] == ["warn"], option
    assert verdict == "pass"


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("option", [
    "--ignore=tests", "--ignore=tests/", "--ignore=./tests/test_billing.py", "--ignore=.",
    "--ignore-glob=tests/*", "--ignore-glob=test*", "--ignore-glob=tests", "--ignore-glob=*_billing.py",
    "--deselect tests/test_billing.py", "--deselect tests/test_billing.py::test_invoice",
    "--deselect=tests/test_billing.py::test_invoice_total[1]",
    "-p no:python", "-p no:unittest", "-p no:warnings", "-p no:doctest", "-p no:randomly",
    SELECTOR, "-k invoice", "--co",
])
def test_a_first_option_that_can_leave_a_test_out_blocks(carrier, option):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": option})})
    assert [severity for severity, _ in hits] == ["high"], option
    assert verdict == "block"


def test_the_reported_option_is_one_that_leaves_a_test_out():
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": "--ignore=docs " + SELECTOR})})
    assert hits == [("high", "CI configuration changed; test command weakened: "
                             "resolved pytest collection option introduced: -m not slow")]


def test_an_existing_config_gaining_a_path_option_still_blocks_through_the_scanners():
    # Disclosed asymmetry: the token scan and the syntax scanner read the
    # existing config's added option and do not evaluate it (#196 184.2).
    before = {"pytest.ini": source("pytest.ini", {"addopts": "-ra"})}
    after = {"pytest.ini": source("pytest.ini", {"addopts": "-ra --ignore=docs"})}
    hits, verdict = judge(before, after, {"docs/conf.py": b"x = 1\n"})
    assert [severity for severity, _ in hits] == ["high"]
    assert verdict == "block"
