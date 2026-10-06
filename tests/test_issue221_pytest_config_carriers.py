"""Issue #221: `.pytest.ini`, `pytest.toml` and `.pytest.toml` are pytest
configuration, so they are ci files and carriers of the resolved collection
inventory, as `pytest.ini` is.

They were production. No CI rule read them, so `--deselect`, `-p no:python` or
a narrowed `testpaths` written into one gave zero findings while the same edit
in `pytest.ini` blocked, and a new `pytest.toml` beside `pytest.ini`, which
pytest 9 reads instead of it, passed with zero findings. The globs are
root-anchored like `pytest.ini`'s, so a nested config stays production
(221.Q1; THREATMODEL row 105, item 5). The carrier matrices of #90 and #173 run
the three carriers too.
"""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

NEW = [".pytest.ini", "pytest.toml", ".pytest.toml"]
HEAD = {
    "app/__init__.py": b"",
    "app/billing.py": b"def total(items):\n    return round(sum(items), 2)\n",
    "tests/test_billing.py": (b"from app.billing import total\n\n\n"
                              b"def test_total():\n    assert total([50.0, 28.75]) == 78.75\n\n\n"
                              b"def test_empty():\n    assert total([]) == 0\n"),
}
TOTAL = "tests/test_billing.py::test_total"


def config(path, **settings):
    """A pytest config in the carrier's own syntax. A list is a list setting:
    a TOML array in a TOML carrier (pytest 9 refuses a string for one in
    pytest.toml), words in an INI one."""
    if path.endswith(".toml"):
        body = "".join(f"{key} = {json.dumps(value)}\n" for key, value in settings.items())
    else:
        body = "".join(f"{key} = {value if isinstance(value, str) else ' '.join(value)}\n"
                       for key, value in settings.items())
    return ("[tool.pytest.ini_options]\n" if path == "pyproject.toml" else "[pytest]\n").encode() + body.encode()


def judge(before, after, *, readers=True):
    """CI_WORKFLOW_TOUCHED findings as (path, severity, escalators, message), and the verdict."""
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path))
               for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    snapshot = {**HEAD, **after}
    kwargs = {"root_reader": snapshot.get}
    if readers:
        kwargs.update(root_path_lister=lambda: sorted(snapshot),
                      root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6), **kwargs)
    return [(f.path, f.severity, list(f.escalators), f.message)
            for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"], verdict


def test_the_root_carriers_are_ci_and_nested_ones_stay_production():
    roles = Config().role_of
    assert [roles(path) for path in ["pytest.ini", *NEW]] == ["ci"] * 4
    for path in ("sub/pytest.ini", "sub/.pytest.ini", "sub/pytest.toml", "sub/.pytest.toml",
                 "pytest.toml.orig", "docs/pytest.toml", "Pytest.toml"):
        assert roles(path) == "prod", path


@pytest.mark.parametrize("path", ["pytest.ini", *NEW])
@pytest.mark.parametrize("words", [["--deselect", TOTAL], ["-p", "no:python"]], ids=["deselect", "no-python"])
def test_an_option_written_into_a_carrier_is_a_weakened_command(path, words):
    # A0-A5: the token scan and the syntax scanner read the three as they
    # read pytest.ini. No path inventory is needed.
    base = config(path, minversion="9.0")
    hits, verdict = judge({path: base}, {path: config(path, minversion="9.0", addopts=words)}, readers=False)
    assert [(p, severity, escalators) for p, severity, escalators, _ in hits] == [
        (path, "high", ["CI_TEST_COMMAND_WEAKENED"])]
    assert verdict == "block"


@pytest.mark.parametrize("path", ["pytest.ini", *NEW])
def test_testpaths_pointed_away_from_the_suite_is_a_weakened_command(path):
    # A6, A7.
    hits, _ = judge({path: config(path, minversion="9.0")},
                    {path: config(path, minversion="9.0", testpaths=["smoke"])}, readers=False)
    assert [(p, severity) for p, severity, _, _ in hits] == [(path, "high")]


@pytest.mark.parametrize("path", ["pytest.ini", *NEW])
def test_a_first_carrier_is_resolved_against_the_suite(path):
    # F0-F3: only the inventory judges a first configuration.
    hits, verdict = judge({}, {path: config(path, python_files=["smoke_*.py"])})
    assert [(p, severity) for p, severity, _, _ in hits] == [(path, "high")]
    assert hits[0][3].endswith(
        "resolved pytest collection excludes 2 existing test(s), including tests/test_billing.py::test_empty")
    assert verdict == "block"


@pytest.mark.parametrize("path", ["pytest.toml", ".pytest.toml"])
def test_a_new_toml_carrier_beside_pytest_ini_governs_the_run(path):
    # D1, D2: pytest 9.1.1 prints `configfile: pytest.toml (WARNING: ignoring
    # pytest config in pytest.ini!)` and runs what the new file says.
    base = {"pytest.ini": config("pytest.ini", testpaths=["tests"])}
    deselect = config(path, testpaths=["tests"], addopts=["--deselect", TOTAL])
    hits, verdict = judge(base, {**base, path: deselect})
    assert [(p, severity) for p, severity, _, _ in hits] == [(path, "high")]
    assert hits[0][3].endswith(f"resolved pytest collection option introduced: --deselect {TOTAL}")
    assert verdict == "block"
    hits, _ = judge(base, {**base, path: config(path, python_files=["smoke_*.py"])})
    assert [(p, severity) for p, severity, _, _ in hits] == [(path, "high")]
    assert "excludes 2 existing test(s)" in hits[0][3]


def test_without_the_inventory_a_new_carrier_beside_pytest_ini_reads_at_warn():
    # A new file has no narrowing family (SPEC §4, first adoption): only the
    # inventory can judge D1 and D2.
    base = {"pytest.ini": config("pytest.ini", testpaths=["tests"])}
    after = {**base, "pytest.toml": config("pytest.toml", testpaths=["tests"], addopts=["--deselect", TOTAL])}
    hits, verdict = judge(base, after, readers=False)
    assert [(p, severity) for p, severity, _, _ in hits] == [("pytest.toml", "warn")]
    assert verdict == "pass"


@pytest.mark.parametrize("existing,added", [("pytest.ini", ".pytest.ini"), ("pytest.toml", "pytest.ini"),
                                            ("pytest.toml", ".pytest.toml")])
def test_a_new_carrier_that_pytest_does_not_read_selects_nothing(existing, added):
    # pytest reads pytest.toml, .pytest.toml, pytest.ini, .pytest.ini in that
    # order: a lower carrier added beside a higher one is ignored.
    base = {existing: config(existing, testpaths=["tests"])}
    hits, verdict = judge(base, {**base, added: config(added, addopts=["--deselect", TOTAL])})
    assert [(p, severity) for p, severity, _, _ in hits] == [(added, "warn")]
    assert verdict == "pass"


def test_deleting_the_carrier_pytest_reads_hands_the_run_to_the_next():
    # An ignored carrier is dormant, not harmless: deleting pytest.toml makes
    # pytest read the pytest.ini beside it, and the inventory judges that.
    dormant = config("pytest.ini", addopts=["--deselect", TOTAL])
    base = {"pytest.toml": config("pytest.toml", testpaths=["tests"]), "pytest.ini": dormant}
    hits, verdict = judge(base, {"pytest.ini": dormant})
    assert [(p, severity) for p, severity, _, _ in hits] == [("pytest.toml", "high")]
    assert hits[0][3].endswith(f"resolved pytest collection option introduced: --deselect {TOTAL}")
    assert verdict == "block"


def test_a_hidden_ini_beside_a_pyproject_governs_the_run():
    base = {"pyproject.toml": b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'}
    hits, _ = judge(base, {**base, ".pytest.ini": config(".pytest.ini", addopts=["--deselect", TOTAL])})
    assert [(p, severity) for p, severity, _, _ in hits] == [(".pytest.ini", "high")]


@pytest.mark.parametrize("source,target", [("pytest.ini", "pytest.toml"), ("pytest.ini", ".pytest.toml"),
                                           ("pytest.ini", ".pytest.ini"), (".pytest.toml", "pytest.ini"),
                                           ("pytest.toml", "pyproject.toml")])
def test_moving_an_identical_config_between_carriers_stays_warn(source, target):
    # E6's relocation rule: the base side of every ci file is the surface a
    # narrowing must be absent from, so a moved `--deselect` is not new.
    settings = {"testpaths": ["tests"], "addopts": ["--strict-markers", "--deselect", "tests/test_billing.py::test_empty"]}
    for readers in (False, True):
        hits, verdict = judge({source: config(source, **settings)}, {target: config(target, **settings)}, readers=readers)
        assert sorted((p, severity) for p, severity, _, _ in hits) == sorted([(source, "warn"), (target, "warn")])
        assert verdict == "pass"


def test_an_edit_that_selects_nothing_stays_warn():
    path = "pytest.toml"
    hits, verdict = judge({path: config(path, minversion="9.0")},
                          {path: config(path, minversion="9.0") + b"xfail_strict = true\n"})
    assert [(p, severity) for p, severity, _, _ in hits] == [(path, "warn")]
    assert verdict == "pass"
