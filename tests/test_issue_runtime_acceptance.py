"""Issue-shaped installation and provider acceptance beyond original fixtures."""
import datetime

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


@pytest.mark.parametrize("install", [
    "billing.total = replacement", "setattr(billing, 'total', replacement)",
    "vars(billing)['total'] = replacement", "billing.__dict__['total'] = replacement",
    "importlib.import_module('app.billing').total = replacement",
    "pytest.MonkeyPatch().setitem(vars(billing), 'total', replacement)",
    "patch.object(billing, 'total', replacement).start()",
])
@pytest.mark.parametrize("scope", ["module", "fixture", "pytest_configure", "pytest_sessionstart", "pytest_collection_modifyitems"])
@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py"])
def test_issue91_spelling_scope_location_matrix(install, scope, path):
    prefix = "import app.billing as billing\nimport importlib\nimport pytest\nfrom unittest.mock import patch\ndef replacement():\n    return 3\n"
    if scope == "module":
        source = prefix + install + "\n"
    elif scope == "fixture":
        source = prefix + "@pytest.fixture(autouse=True)\ndef standin():\n    " + install + "\n"
    else:
        source = prefix + f"def {scope}():\n    " + install + "\n"
    findings = judge({}, {path: source.encode()}, {"tests/test_total.py": MODULE_TEST})
    assert any(f.rule == "CONFTEST_PATCHES_PROD" and f.severity == "high" for f in findings), (path, scope, install)


@pytest.mark.parametrize("install", ["setattr(request.module, 'total', replacement)",
    "request.module.total = replacement", "vars(request.module)['total'] = replacement",
    "monkeypatch.setitem(vars(request.module), 'total', replacement)"])
def test_issue85_request_module_spellings(install):
    source = ("import pytest\ndef replacement():\n    return 3\n@pytest.fixture(autouse=True)\ndef standin(request, monkeypatch):\n"
              "    original = getattr(request.module, 'total', None)\n    " + install + "\n    yield\n    setattr(request.module, 'total', original)\n")
    assert any(f.rule == "CONFTEST_PATCHES_PROD" for f in judge({}, {"tests/conftest.py": source.encode()}, {"tests/test_total.py": IMPORT_TEST}))


@pytest.mark.parametrize("replacement", ["reference_total", "lambda: 3", "partial(reference_total)"])
def test_issue88_callable_binding_spellings(replacement):
    prefix = b"from functools import partial\ndef reference_total():\n    return 3\n"
    before = prefix + IMPORT_TEST
    after = before.replace(b"    assert", f"    total = {replacement}\n    assert".encode())
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))


def test_issue88_fixture_parameter_replaces_existing_imported_subject():
    fixture = b"import pytest\n@pytest.fixture\ndef total():\n    return lambda: 3\n"
    after = IMPORT_TEST.replace(b"test_total():", b"test_total(total):")
    assert any(f.rule in {"TEST_PATCHES_SUBJECT", "CONFTEST_PATCHES_PROD"} for f in judge(
        {"tests/test_total.py": IMPORT_TEST}, {"tests/test_total.py": after, "tests/conftest.py": fixture}))


@pytest.mark.parametrize("fixture,result_test", [
    (b"import pytest\nfrom app.billing import total as original\n@pytest.fixture\ndef total():\n    return original\n", IMPORT_TEST.replace(b"test_total():", b"test_total(total):")),
    (b"import pytest\nfrom app.billing import total as original\n@pytest.fixture\ndef total():\n    return original()\n", IMPORT_TEST.replace(b"test_total():", b"test_total(total):").replace(b"assert total()", b"assert total")),
])
def test_issue88_fixture_forwarding_or_computing_original_subject_is_honest(fixture, result_test):
    assert not any(f.rule in {"TEST_PATCHES_SUBJECT", "CONFTEST_PATCHES_PROD"} for f in judge(
        {"tests/test_total.py": IMPORT_TEST}, {"tests/test_total.py": result_test, "tests/conftest.py": fixture}))

