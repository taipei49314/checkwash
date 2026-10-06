"""A pytest file under a snapshot directory is judged as a test beside its snapshot role (#219).

`tests/golden/test_x.py` resolves to the `snapshot` role, so it was never
parsed or judged as a test: moving `tests/test_x.py` there blocked with a
false "test unit disappeared" for every unit, although pytest still collects
the destination, and a test already living there was judged only by the
snapshot rules (deleting it passed with zero findings).

Ruling 219.Q1: a Python file has test obligations exactly when
`collectable(path)` holds, whatever its published role. One predicate serves
the obligations and rename continuity, as 197.Q2 rules for JS. Ruling 219.Q2:
the snapshot role keeps its own rules, and the test obligations add theirs.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.ir.model import judged_as_test

TODAY = datetime.date(2026, 10, 5)
BODY = (
    b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n\n\n"
    b"def test_other():\n    assert total() == 78.75\n"
)
WEAK = BODY.replace(b"def test_total():\n    assert total() == 78.75", b"def test_total():\n    assert total()")
SKIP = BODY.replace(b"def test_other", b"import pytest\n\n\n@pytest.mark.skip(reason=\"flaky\")\ndef test_other")
HEAD = {
    "app/__init__.py": b"",
    "app/billing.py": b"def total():\n    return 78.75\n",
    "app/util.py": b"def f():\n    return 2\n",
}
GOLDEN = "tests/golden/test_x.py"


def run(*changes):
    snapshot = dict(HEAD)
    for change in changes:
        if change.after is not None:
            snapshot[change.path] = change.after
    ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY, head_reader=snapshot.get)
    return ir, sorted((f.rule, f.severity, f.path, f.unit) for f in findings), verdict


def move(dest, status="renamed"):
    return FileChange(dest, status, BODY, BODY, old_path="tests/test_x.py")


# --- continuity: pytest still collects the destination (219.Q1) -----------------------------


@pytest.mark.parametrize("dest", ["tests/golden/test_x.py", "tests/expected/test_x.py",
                                  "tests/__snapshots__/test_x.py"])
@pytest.mark.parametrize("status", ["modified", "renamed"])
def test_a_move_into_a_snapshot_directory_removes_no_test(dest, status):
    ir, findings, verdict = run(move(dest, status))
    assert verdict == "pass"
    # The supervised-role rule still expands the move, as it does a JS
    # test's from tests/: the units are held as moved, at info.
    assert all(severity == "info" for _rule, severity, _path, _unit in findings)
    destination = next(file for file in ir.files if file.path == dest)
    assert (destination.role, destination.test_obligations) == ("snapshot", True)


def test_the_delete_and_add_form_of_the_move_passes_too():
    _ir, findings, verdict = run(FileChange("tests/test_x.py", "deleted", BODY, None),
                                 FileChange(GOLDEN, "added", None, BODY))
    assert verdict == "pass"
    assert all(severity == "info" for _rule, severity, _path, _unit in findings)


def test_a_move_within_the_test_role_is_unchanged():
    assert run(move("tests/unit/test_x.py"))[1:] == ([], "pass")


@pytest.mark.parametrize("dest", [
    pytest.param("tests/.attic/test_x.py", id="dot-directory"),
    pytest.param("build/test_x.py", id="build-output"),
    pytest.param(".github/workflows/test_x.py", id="ci-dot-directory"),
    pytest.param("tests/golden/x_checks.py", id="not-a-test-name"),
])
def test_a_move_out_of_collection_still_removes_the_tests(dest):
    _ir, findings, verdict = run(move(dest))
    assert verdict == "block"
    assert ("TEST_DISABLED", "high", "tests/test_x.py", "test_total") in findings
    assert ("TEST_DISABLED", "high", "tests/test_x.py", "test_other") in findings


# --- obligations: a test there is judged as a test, and as a snapshot (219.Q2) ---------------


def test_a_weakened_assertion_reports_both_roles_rules():
    _ir, findings, verdict = run(FileChange(GOLDEN, "modified", BODY, WEAK))
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _path, _unit in findings] == [
        ("ASSERT_WEAKENED", "high"), ("EXPECTED_VALUE_CHANGED", "high")]


def test_an_added_skip_reports_both_roles_rules():
    _ir, findings, verdict = run(FileChange(GOLDEN, "modified", BODY, SKIP))
    assert verdict == "block"
    assert [(rule, severity, unit) for rule, severity, _path, unit in findings] == [
        ("EXPECTED_VALUE_CHANGED", "high", None), ("TEST_DISABLED", "high", "test_other")]


def test_deleting_it_removes_its_tests():
    _ir, findings, verdict = run(FileChange(GOLDEN, "deleted", BODY, None))
    assert verdict == "block"
    assert findings == [("TEST_DISABLED", "high", GOLDEN, "test_other"),
                        ("TEST_DISABLED", "high", GOLDEN, "test_total")]


def test_beside_a_production_edit_the_weakening_is_judged_as_one():
    # The file's own test logic changed, so SNAPSHOT_CODE_COCHANGE stands
    # down, as it does for any test logic change; the test rules judge it.
    _ir, findings, verdict = run(
        FileChange(GOLDEN, "modified", BODY, WEAK),
        FileChange("app/util.py", "modified", b"def f():\n    return 1\n", b"def f():\n    return 2\n"),
    )
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _path, _unit in findings] == [("ASSERT_WEAKENED", "high")]


@pytest.mark.parametrize("path", [
    pytest.param("tests/golden/data.py", id="not-a-test-name"),
    pytest.param("tests/golden/x_checks.py", id="checks-suffix"),
])
def test_a_python_file_pytest_does_not_collect_stays_a_snapshot_only(path):
    ir, findings, _verdict = run(FileChange(path, "modified", BODY, WEAK))
    assert [(file.role, file.test_obligations) for file in ir.files] == [("snapshot", False)]
    assert not judged_as_test(ir.files[0])
    assert [rule for rule, _severity, _path, _unit in findings] == ["EXPECTED_VALUE_CHANGED"]


@pytest.mark.parametrize("path,role,obligations", [
    ("tests/golden/test_x.py", "snapshot", True),
    ("tests/expected/test_x.py", "snapshot", True),
    ("tests/golden/sub/x_test.py", "snapshot", True),
    ("tests/test_x.py", "test", False),
    ("tests/golden/expected.txt", "snapshot", False),
])
def test_obligations_follow_collectability(path, role, obligations):
    ir, _findings, _verdict = run(FileChange(path, "added", None, BODY))
    assert [(file.role, file.test_obligations) for file in ir.files] == [(role, obligations)]


# --- a test that lives there: its moves are judged as a test's (219.Q1) ----------------------


def test_a_move_within_the_snapshot_directory_is_an_edit():
    ir, findings, verdict = run(FileChange("tests/golden/test_y.py", "renamed", BODY, BODY, old_path=GOLDEN))
    assert (findings, verdict) == ([], "pass")
    assert [(file.role, file.test_obligations) for file in ir.files] == [("snapshot", True)]


def test_moving_it_back_into_tests_removes_no_test():
    _ir, findings, verdict = run(FileChange("tests/test_x.py", "renamed", BODY, BODY, old_path=GOLDEN))
    assert verdict == "pass"
    assert {(rule, severity, path) for rule, severity, path, _unit in findings} == {
        ("TEST_DISABLED", "info", GOLDEN)}


@pytest.mark.parametrize("dest", ["tests/golden/x_checks.py", "app/legacy.py"])
def test_moving_it_out_of_collection_removes_its_tests(dest):
    _ir, findings, verdict = run(FileChange(dest, "renamed", BODY, BODY, old_path=GOLDEN))
    assert verdict == "block"
    assert findings == [("TEST_DISABLED", "high", GOLDEN, "test_other"),
                        ("TEST_DISABLED", "high", GOLDEN, "test_total")]


# --- whatever its published role: a project's own globs (219.Q1) ----------------------------


def test_a_collectable_file_a_project_calls_production_keeps_that_role_and_is_judged_as_a_test():
    # Role globs replace the defaults, so a project can leave src/pkg/test_x.py
    # out of the test role. pytest still collects it: it keeps the role the
    # project gave it, which E7 reads, and every test rule judges it.
    config = Config()
    config.roles["test"] = ["tests/**"]
    path = "src/pkg/test_x.py"
    snapshot = {**HEAD, path: WEAK}
    ir, findings, verdict = analyze([FileChange(path, "modified", BODY, WEAK)], config, Contract(), [], TODAY,
                                    head_reader=snapshot.get)
    assert [(file.role, file.test_obligations) for file in ir.files] == [("prod", True)]
    assert verdict == "block"
    assert [(f.rule, f.severity, f.unit) for f in findings] == [("ASSERT_WEAKENED", "high", "test_total")]


# --- one predicate wherever a head-side search asks for a collected test (219.Q1) ------------


def _search(snapshot):
    return lambda needles: [p for p, data in sorted(snapshot.items())
                            if data is not None and any(n.encode() in data for n in needles)]


@pytest.mark.parametrize("copy,credited", [
    ("tests/unit/test_copy.py", True),
    ("tests/golden/test_copy.py", True),
    ("tests/golden/copy_checks.py", False),
])
def test_a_copy_pytest_still_collects_keeps_a_deleted_duplicate_running(copy, credited):
    kept = b"from app.billing import total\n\n\ndef test_other():\n    assert total() == 78.75\n"
    snapshot = {**HEAD, copy: BODY, "tests/test_x.py": kept}
    _ir, findings, verdict = analyze([FileChange("tests/test_x.py", "modified", BODY, kept)], Config(), Contract(),
                                     [], TODAY, head_reader=snapshot.get, head_searcher=_search(snapshot))
    assert [(f.rule, f.unit) for f in findings] == [("TEST_DISABLED", "test_total")]
    assert ("DUPLICATE_REMAINS" in findings[0].deescalators) is credited
    assert verdict == ("pass" if credited else "block")


@pytest.mark.parametrize("importer,reported", [
    ("tests/test_calc.py", True),
    ("tests/golden/test_calc.py", True),
    ("tests/golden/calc_checks.py", False),
])
def test_an_unchanged_importer_pytest_collects_loses_a_root_helpers_oracle(importer, reported):
    helper = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
    gutted = b"def assert_equal(actual, expected):\n    pass\n"
    caller = b"from calc import add\nfrom test_helpers import assert_equal\n\ndef test_add():\n    assert_equal(add(2, 3), 5)\n"
    snapshot = {importer: caller, "test_helpers.py": gutted}
    _ir, findings, verdict = analyze(
        [FileChange("test_helpers.py", "modified", helper, gutted)], Config(), Contract(), [], TODAY,
        head_reader=snapshot.get, head_searcher=_search(snapshot),
        root_reader=snapshot.get, root_searcher=_search(snapshot),
    )
    removed = [(f.rule, f.severity, f.path) for f in findings if f.rule == "ASSERT_REMOVED"]
    assert removed == ([("ASSERT_REMOVED", "high", importer)] if reported else [])
    assert verdict == ("block" if reported else "pass")


@pytest.mark.parametrize("directory", ["tests/unit", "tests/golden"])
def test_a_test_pytest_collects_is_in_the_runtime_shadow_inventory(directory):
    from checkwash.shadow import find_runtime_subject_shadows

    test, stand_in = f"{directory}/test_total.py", f"{directory}/src/billing.py"
    snapshot = {"src/billing.py": b"def total():\n    return 3\n",
                test: b"from src.billing import total\n\n\ndef test_total():\n    assert total() == 3\n",
                stand_in: b"def total():\n    return 3  # stand-in\n"}
    hits = find_runtime_subject_shadows(
        [FileChange(stand_in, "added", None, snapshot[stand_in])], Config(),
        head_path_lister=lambda: sorted(snapshot),
        head_batch_reader=lambda paths: {path: snapshot.get(path) for path in paths},
        include_equivalent=True,
    )
    assert [(hit.test_path, hit.module, hit.before_provider, hit.after_provider) for hit in hits] == [
        (test, "src.billing", "src/billing.py", stand_in)]


@pytest.mark.parametrize("directory", ["tests", "tests/golden"])
def test_a_package_boundary_change_reaches_the_import_root_of_a_test_pytest_collects(directory):
    # Deleting src/app/__init__.py turns app into a namespace package, so a
    # same-named directory beside the test, on its prepended import root,
    # now supplies app.normalize.
    from checkwash.shadow import find_runtime_subject_shadows

    sources = {
        "pytest.ini": b"[pytest]\npythonpath = src\n",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        f"{directory}/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        f"{directory}/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize('X') == 'x'\n"
        ),
    }
    hits = find_runtime_subject_shadows(
        [FileChange("src/app/__init__.py", "deleted", b"", None)], Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
    )
    assert [(hit.before_provider, hit.after_provider, hit.test_path) for hit in hits] == [
        ("src/app/normalize.py", f"{directory}/app/normalize.py", f"{directory}/test_normalize.py")]


@pytest.mark.parametrize("directory", ["tests", "tests/golden"])
def test_a_runner_glob_target_expands_over_the_tests_pytest_collects(directory):
    from checkwash.shadow import find_runtime_subject_shadows

    before = f"#!/bin/sh\nPYTHONPATH=src pytest {directory}/test_*.py\n".encode()
    after = f"#!/bin/sh\nPYTHONPATH=standins:src pytest {directory}/test_*.py\n".encode()
    sources = {
        "src/alpha/value.py": b"def value():\n    return 'prod-alpha'\n",
        "standins/alpha/value.py": b"def value():\n    return 'shadow-alpha'\n",
        f"{directory}/test_alpha.py": (
            b"from alpha.value import value\n\n"
            b"def test_value():\n    assert value() == 'shadow-alpha'\n"
        ),
        "scripts/test.sh": after,
    }
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)], Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
    )
    assert [(hit.module, hit.test_path) for hit in hits] == [("alpha.value", f"{directory}/test_alpha.py")]


@pytest.mark.parametrize("directory", ["tests", "tests/golden"])
def test_an_import_mode_change_reaches_the_import_root_of_a_test_pytest_collects(directory):
    # --import-mode=prepend puts each test's own directory first on sys.path,
    # so app/value.py beside the test now supplies app.value.
    from checkwash.shadow import find_runtime_subject_shadows

    before = b"#!/bin/sh\nPYTHONPATH=src pytest --import-mode=append tests\n"
    after = b"#!/bin/sh\nPYTHONPATH=src pytest --import-mode=prepend tests\n"
    sources = {
        "src/app/value.py": b"VALUE = 'prod'\n",
        f"{directory}/app/value.py": b"VALUE = 'shadow'\n",
        f"{directory}/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'shadow'\n"
        ),
        "scripts/test.sh": after,
    }
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)], Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
    )
    assert [(hit.before_provider, hit.after_provider, hit.test_path) for hit in hits] == [
        ("src/app/value.py", f"{directory}/app/value.py", f"{directory}/test_value.py")]
