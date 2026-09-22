"""Issue-shaped installation and provider acceptance beyond original fixtures."""
import datetime
import json
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping

PROD = b"def total():\n    return 1\n"
MODULE_TEST = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
IMPORT_TEST = b"from app.billing import total\ndef test_total():\n    assert total() == 3\n"


def judge(before, after, common=None):
    common = {"app/__init__.py": b"", "app/billing.py": PROD, **(common or {})}
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path)) for path in sorted(before.keys() | after.keys())
               if before.get(path) != after.get(path)]
    snapshot = {**common, **after}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_path_lister=lambda: sorted(snapshot),
                   root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})[1]



def shadow_judge(before, after):
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path)) for path in sorted(before.keys() | after.keys())
               if before.get(path) != after.get(path)]
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=after.get, root_searcher=lambda needles: search_source_mapping(after, needles),
                   root_path_lister=lambda: sorted(after),
                   root_batch_reader=lambda paths: {p: after.get(p) for p in paths})[1]


@pytest.mark.parametrize("initializer", [None, b"from pkgutil import extend_path\n__path__ = extend_path(__path__, __name__)\n"])
def test_issue86_namespace_and_extend_path_shadow_actual_oracle(initializer):
    before = {"src/billing.py": PROD, "tests/test_billing.py": IMPORT_TEST.replace(b"app.billing", b"src.billing")}
    after = {**before, "tests/src/billing.py": b"def total():\n    return 3\n"}
    if initializer is not None:
        after["tests/src/__init__.py"] = initializer
    assert any(f.rule == "TEST_PATCHES_SUBJECT" and f.severity == "high" for f in shadow_judge(before, after))


@pytest.mark.parametrize("path", ["pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"])
@pytest.mark.parametrize("initializer", [b"", b"from pkgutil import extend_path\n__path__ = extend_path(__path__, __name__)\n"])
def test_issue95_root_package_pythonpath_carrier_matrix(path, initializer):
    section = "[tool.pytest.ini_options]" if path == "pyproject.toml" else "[tool:pytest]" if path == "setup.cfg" else "[pytest]"
    def config(value):
        return (section + "\npythonpath = " + (json.dumps(value) if path == "pyproject.toml" else value) + "\n").encode()
    before = {"src/app/__init__.py": b"", "src/app/billing.py": PROD,
              "tests/test_billing.py": IMPORT_TEST, path: config("src")}
    after = {**before, "app/__init__.py": initializer, "app/billing.py": b"def total():\n    return 3\n", path: config(". src")}
    assert any(f.rule == "TEST_PATCHES_SUBJECT" and f.severity == "high" for f in shadow_judge(before, after))


@pytest.mark.parametrize("route", ["conftest", "runner"])
def test_issue95_literal_search_order_routes_reach_competing_provider(route):
    before = {"src/app/billing.py": PROD, "tests/test_billing.py": IMPORT_TEST,
              "standins/app/billing.py": b"def total():\n    return 3\n"}
    if route == "conftest":
        before["pytest.ini"] = b"[pytest]\npythonpath = src\n"
        after = {**before, "conftest.py": b"import sys\nsys.path.insert(0, 'standins')\n"}
    else:
        before["scripts/test.sh"] = b"#!/bin/sh\nPYTHONPATH=src pytest tests\n"
        after = {**before, "scripts/test.sh": b"#!/bin/sh\nPYTHONPATH=standins:src pytest tests\n"}
    assert any(f.rule == "TEST_PATCHES_SUBJECT" and f.severity == "high" for f in shadow_judge(before, after))


def test_issue95_duplicate_provider_that_never_wins_remains_silent():
    before = {"src/app/__init__.py": b"", "src/app/billing.py": PROD,
              "tests/test_billing.py": IMPORT_TEST, "pytest.ini": b"[pytest]\npythonpath = src\n"}
    after = {**before, "app/__init__.py": b"", "app/billing.py": b"def total():\n    return 3\n"}
    assert not any(f.rule == "TEST_PATCHES_SUBJECT" for f in shadow_judge(before, after))
