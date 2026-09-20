"""Resolved collection configuration and override spellings from issue #90."""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


CARRIERS = ["pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"]
TESTS = {"tests/test_add.py": b"def test_add():\n    assert 1 == 2\n",
         "tests/test_padding.py": b"def test_padding():\n    assert True\n",
         "checks/test_check.py": b"def test_check():\n    assert True\n"}


def source(path, settings):
    section = "[tool.pytest.ini_options]" if path == "pyproject.toml" else "[tool:pytest]" if path == "setup.cfg" else "[pytest]"
    return (section + "\n" + "".join(f"{key} = {json.dumps(value) if path == 'pyproject.toml' else value}\n" for key, value in settings.items())).encode()


def judge(before, after, common=None):
    common = TESTS if common is None else common
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path)) for path in sorted(before.keys() | after.keys())
               if before.get(path) != after.get(path)]
    snapshot = {**common, **after}
    result = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 21),
                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return [f for f in result[1] if f.rule == "CI_WORKFLOW_TOUCHED" and f.severity == "high"]


@pytest.mark.parametrize("path", CARRIERS)
@pytest.mark.parametrize("option", ["--co", "--collect-only", "--ignore-glob=tests/test_a*", "--ignore-glob tests/test_a*",
    "-k padding", "-kpadding", "-m public", "-mpublic", "--ignore=tests/test_add.py", "--deselect tests/test_add.py::test_add",
    "-p no:python", "-pno:python", "-o testpaths=tests/test_padding.py", "-otestpaths=tests/test_padding.py",
    "--override-ini=testpaths=tests/test_padding.py", "--override-ini testpaths=tests/test_padding.py"])
@pytest.mark.parametrize("mode", ["introduce", "existing", "relocate"])
def test_spelling_by_config_carrier_by_transition_matrix(path, option, mode):
    before_path = next(p for p in CARRIERS if p != path) if mode == "relocate" else path
    before = {} if mode == "introduce" else {before_path: source(before_path, {"testpaths": "tests"})}
    after = {path: source(path, {"testpaths": "tests", "addopts": option})}
    assert judge(before, after), (path, mode, option)


@pytest.mark.parametrize("path", CARRIERS)
@pytest.mark.parametrize("key,before_value,after_value", [
    ("testpaths", "tests checks", "tests"),
    ("python_files", "test_*.py", "test_p[ae]*.py"),
    ("python_functions", "test", "test_p[ae]*"),
    ("norecursedirs", "build", "build checks"),
])
def test_existing_and_relocated_literal_settings_use_actual_inventory(path, key, before_value, after_value):
    before_path = next(p for p in CARRIERS if p != path)
    assert judge({before_path: source(before_path, {key: before_value})},
                 {path: source(path, {key: after_value})})


@pytest.mark.parametrize("path", CARRIERS)
def test_first_configuration_only_blocks_when_it_excludes_existing_tests(path):
    assert judge({}, {path: source(path, {"testpaths": "tests"})})
    assert not judge({}, {path: source(path, {"testpaths": "tests checks"})})
    assert not judge({}, {path: source(path, {"testpaths": "tests/nothing"})})


@pytest.mark.parametrize("before_path", CARRIERS)
@pytest.mark.parametrize("after_path", CARRIERS)
def test_equal_config_moves_and_broadening_remain_nonblocking(before_path, after_path):
    before = {before_path: source(before_path, {"testpaths": "tests", "addopts": "-k padding"})}
    after = {after_path: source(after_path, {"testpaths": "tests", "addopts": "-k padding"})}
    assert not judge(before, after)
    after = {after_path: source(after_path, {"testpaths": "tests checks", "addopts": "-k padding"})}
    assert not judge(before, after)


def test_last_override_wins_and_equivalent_override_is_not_narrowing():
    before = {"pytest.ini": source("pytest.ini", {"testpaths": "tests"})}
    after = {"pytest.ini": source("pytest.ini", {"testpaths": "tests", "addopts": "-o testpaths=tests/test_padding.py -o testpaths=tests"})}
    assert not judge(before, after)


def test_override_replacing_an_existing_override_is_compared_by_value():
    before = {"pytest.ini": source("pytest.ini", {"addopts": "-o testpaths=tests"})}
    after = {"pytest.ini": source("pytest.ini", {"addopts": "--override-ini testpaths=tests/test_padding.py"})}
    assert judge(before, after)


def test_python_classes_patterns_compare_actual_plain_test_methods():
    common = {"tests/test_objects.py": b"class TestA:\n    def test_a(self):\n        assert False\nclass TestB:\n    def test_b(self):\n        assert True\n"}
    assert judge({"pytest.ini": source("pytest.ini", {"python_classes": "Test"})},
                 {"pytest.ini": source("pytest.ini", {"python_classes": "Test[B-C]"})}, common)


def test_config_unrelated_metadata_change_avoids_inventory():
    from checkwash.collection_inventory import collection_inventory_changes

    def forbidden():
        raise AssertionError("metadata must not enumerate repository sources")

    assert collection_inventory_changes([FileChange("pyproject.toml", "modified", b"[project]\nversion='1'\n", b"[project]\nversion='2'\n")],
                                        Config(), path_lister=forbidden, batch_reader=lambda paths: {}) == []


def test_explicit_runner_targets_do_not_inherit_testpaths_from_root_config():
    # pytest tests checks ignores testpaths; adding the config does not omit checks.
    common = {**TESTS, "scripts/test.sh": b"#!/bin/sh\npytest tests checks\n"}
    assert not judge({}, {"pytest.ini": source("pytest.ini", {"testpaths": "tests"})}, common)


def test_relative_testpaths_excludes_the_same_inventory_as_normalized_spelling():
    assert judge({}, {"pytest.ini": source("pytest.ini", {"testpaths": "./tests"})})


def test_inactive_lower_priority_config_does_not_change_actual_inventory():
    common = {**TESTS, "pytest.ini": source("pytest.ini", {"testpaths": "tests checks"})}
    assert not judge({}, {"pyproject.toml": source("pyproject.toml", {"testpaths": "tests"})}, common)
