"""Assignment/setattr installation matrix on main's strict snapshot API.

The before/head source is data, never executed by these detector tests.
Qualification runs belong on the authorized pool, not a developer machine.
"""

import datetime

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.frontends.python.standin_installations import _candidate, installation_events
from checkwash.ir.model import IR, DiffGlobals


PROD = b"def total():\n    return 1\n"
TEST = b"from app.billing import total\ndef test_total():\n    assert total() == 3\n"


def judge(before, after, unchanged=None):
    common = {"app/__init__.py": b"", "app/billing.py": PROD, **(unchanged or {})}
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path)) for path in sorted(before.keys() | after.keys())
               if before.get(path) != after.get(path)]
    snapshot = {**common, **after}
    for path in before.keys() - after.keys():
        snapshot.pop(path, None)
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_path_lister=lambda: sorted(snapshot),
                   root_batch_reader=lambda paths: {path: snapshot.get(path) for path in paths})


def hits(result, rule="TEST_PATCHES_SUBJECT"):
    return [finding for finding in result[1] if finding.rule == rule]


@pytest.mark.parametrize("install", [
    "billing.total = lambda: 3",
    "setattr(billing, 'total', lambda: 3)",
    "vars(billing)['total'] = lambda: 3",
    "billing.__dict__['total'] = lambda: 3",
    "__imported_setattr(billing, 'total', lambda: 3)",
])
def test_local_attribute_spellings_share_the_reached_installation_predicate(install):
    prefix = "import app.billing as billing\nfrom builtins import setattr as __imported_setattr\n"
    before = (prefix + "def test_total():\n    assert billing.total() == 3\n").encode()
    after = (prefix + f"def test_total():\n    {install}\n    assert billing.total() == 3\n").encode()
    found = hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))
    assert len(found) == 1
    assert found[0].severity == "high"
    assert "app.billing.total" in found[0].message


@pytest.mark.parametrize("replacement", ["reference_total", "lambda: 3"])
def test_plain_local_import_binding_assignment_closes_issue_88(replacement):
    prefix = "from app.billing import total\ndef reference_total():\n    return 3\n"
    before = (prefix + "def test_total():\n    assert total() == 3\n").encode()
    after = (prefix + f"def test_total():\n    total = {replacement}\n    assert total() == 3\n").encode()
    assert len(hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))) == 1


@pytest.mark.parametrize("scope", ["module", "fixture", "pytest_configure", "pytest_sessionstart",
                                   "pytest_collection_modifyitems", "pytest_runtest_setup"])
@pytest.mark.parametrize("location", ["conftest.py", "tests/conftest.py"])
def test_conftest_scope_matrix_closes_issue_91(scope, location):
    body = "billing.total = lambda: 3"
    prefix = "import app.billing as billing\nimport pytest\n"
    if scope == "module":
        source = prefix + body + "\n"
    elif scope == "fixture":
        source = prefix + "@pytest.fixture(autouse=True)\ndef standin():\n    " + body + "\n"
    else:
        source = prefix + f"def {scope}():\n    {body}\n"
    # Fixture/runtest installation happens after from-import capture. Use an
    # imported module object so these cases truly execute the replaced attr.
    test = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
    result = judge({}, {location: source.encode()}, {"tests/test_total.py": test})
    found = hits(result, "CONFTEST_PATCHES_PROD")
    assert len(found) == 1 and found[0].path == location


@pytest.mark.parametrize("install", [
    "setattr(request.module, 'total', reference_total)",
    "request.module.total = reference_total",
    "vars(request.module)['total'] = reference_total",
])
def test_request_module_fixture_rebinding_closes_issue_85(install):
    source = ("import pytest\ndef reference_total():\n    return 3\n"
              "@pytest.fixture(autouse=True)\ndef standin(request):\n"
              "    original = getattr(request.module, 'total', None)\n"
              f"    {install}\n    yield\n    setattr(request.module, 'total', original)\n")
    result = judge({}, {"tests/conftest.py": source.encode()}, {"tests/test_total.py": TEST})
    assert len(hits(result, "CONFTEST_PATCHES_PROD")) == 1


def test_literal_importlib_module_assignment_has_first_party_identity():
    source = b"import importlib\nimportlib.import_module('app.billing').total = lambda: 3\n"
    assert len(hits(judge({}, {"conftest.py": source}, {"tests/test_total.py": TEST}), "CONFTEST_PATCHES_PROD")) == 1


def test_sys_modules_replacement_reaches_a_later_test_import():
    source = b"import sys\nfrom types import SimpleNamespace\nsys.modules['app.billing'] = SimpleNamespace(total=lambda: 3)\n"
    assert len(hits(judge({}, {"conftest.py": source}, {"tests/test_total.py": TEST}), "CONFTEST_PATCHES_PROD")) == 1


def test_sys_modules_fixture_does_not_change_an_already_captured_import():
    source = (b"import pytest\nimport sys\nfrom types import SimpleNamespace\n"
              b"@pytest.fixture(autouse=True)\ndef replace_module():\n"
              b"    sys.modules['app.billing'] = SimpleNamespace(total=lambda: 3)\n")
    assert not hits(judge({}, {"conftest.py": source}, {"tests/test_total.py": TEST}), "CONFTEST_PATCHES_PROD")


def test_attribute_fixture_does_not_rewrite_a_captured_from_import():
    source = (b"import pytest\nimport app.billing as billing\n"
              b"@pytest.fixture(autouse=True)\ndef replace_module():\n"
              b"    setattr(billing, 'total', lambda: 3)\n")
    assert not hits(judge({}, {"conftest.py": source}, {"tests/test_total.py": TEST}), "CONFTEST_PATCHES_PROD")


@pytest.mark.parametrize("body", [
    "assert billing.total() == 3\n    setattr(billing, 'total', lambda: 3)",
    "original = billing.total\n    setattr(billing, 'total', lambda: 3)\n    billing.total = original\n    assert billing.total() == 3",
    "setattr(billing, 'unrelated', lambda: 3)\n    assert billing.total() == 3",
    "setattr = lambda *args: None\n    setattr(billing, 'total', lambda: 3)\n    assert billing.total() == 3",
])
def test_installation_order_restoration_target_and_builtin_controls(body):
    before = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
    after = ("import app.billing as billing\ndef test_total():\n    " + body + "\n").encode()
    assert not hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))


def test_a_result_captured_before_restoration_still_used_the_standin():
    before = b"import app.billing as billing\ndef test_total():\n    result = billing.total()\n    assert result == 3\n"
    after = (b"import app.billing as billing\ndef test_total():\n    original = billing.total\n"
             b"    billing.total = lambda: 3\n    result = billing.total()\n    billing.total = original\n    assert result == 3\n")
    assert len(hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))) == 1


def test_a_new_mocking_test_has_no_existing_oracle():
    source = b"import app.billing as billing\ndef test_new():\n    setattr(billing, 'total', lambda: 3)\n    assert billing.total() == 3\n"
    assert not hits(judge({}, {"tests/test_new.py": source}))


def test_existing_installation_reformat_is_not_a_new_effect():
    before = b"import app.billing as billing\ndef test_total():\n    billing.total = lambda: 3\n    assert billing.total() == 3\n"
    after = before.replace(b"billing.total = lambda: 3", b"billing.total = (lambda : 3)")
    assert not hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after}))


def test_unused_fixture_and_fixture_teardown_are_not_live_installations():
    for body in ("billing.total = lambda: 3", "yield\n    billing.total = lambda: 3"):
        decorator = "@pytest.fixture" if not body.startswith("yield") else "@pytest.fixture(autouse=True)"
        source = (f"import pytest\nimport app.billing as billing\n{decorator}\ndef standin():\n    {body}\n").encode()
        test = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
        assert not hits(judge({}, {"conftest.py": source}, {"tests/test_total.py": test}), "CONFTEST_PATCHES_PROD")


def test_stdlib_setattr_is_hygiene():
    before = b"import time\ndef test_time():\n    assert time.time() > 0\n"
    after = b"import time\ndef test_time():\n    setattr(time, 'time', lambda: 3)\n    assert time.time() > 0\n"
    assert not hits(judge({"tests/test_time.py": before}, {"tests/test_time.py": after}))


def test_legacy_diff_only_api_keeps_ordinary_conftest_assignment_coverage():
    changes = [FileChange("conftest.py", "modified", b"collect_ignore = []\n",
                          b"collect_ignore = []\ncollect_ignore[:] = ['tests/test_total.py']\n"),
               FileChange("tests/test_total.py", "modified", TEST, TEST)]
    result = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12))
    assert any(f.rule == "TEST_DISABLED" for f in result[1])


def test_empty_ancestor_conftest_is_valid_installation_context():
    before = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
    after = before.replace(b"    assert", b"    billing.total = lambda: 3\n    assert")
    assert len(hits(judge({"tests/test_total.py": before}, {"tests/test_total.py": after},
                          {"conftest.py": b""}))) == 1


def test_legacy_strict_search_discovers_unchanged_installation_consumers():
    source = b"import app.billing as billing\nbilling.total = lambda: 3\n"
    snapshot = {"app/__init__.py": b"", "app/billing.py": PROD,
                "conftest.py": source, "tests/test_total.py": TEST}
    result = analyze([FileChange("conftest.py", "added", None, source)],
                     Config(), Contract(), [], datetime.date(2026, 9, 12),
                     root_reader=snapshot.get,
                     root_searcher=lambda needles: search_source_mapping(snapshot, needles))
    assert len(hits(result, "CONFTEST_PATCHES_PROD")) == 1


@pytest.mark.parametrize("before,after", [
    (b"import sys\nsys.path[:] = ['src']\n", b"import sys\nsys.path[:] = ['app']\n"),
    (b"import app.billing as billing\nbilling.total = lambda: 3\n",
     b"import app.billing as billing\nbilling.total = (lambda : 3)\n"),
])
def test_unrelated_or_unchanged_installation_does_not_reverse_scan(before, after):
    def forbidden(_needles):
        raise AssertionError("unchanged or stdlib setup must not inventory consumers")

    ir = IR(base="base", head="head", globals=DiffGlobals())
    assert installation_events(ir, [FileChange("conftest.py", "modified", before, after)], Config(),
                               root_reader=lambda path: None, root_searcher=forbidden) == []


def test_installation_source_byte_limit_is_checked_before_parsing(monkeypatch):
    monkeypatch.setattr("checkwash.frontends.python.standin_installations._MAX_SOURCE_BYTES", 32)
    with pytest.raises(EngineError, match="source exceeds the byte limit"):
        _candidate(b"x = " + b"1" * 33)


def test_installation_consumer_reads_share_a_total_budget(monkeypatch):
    monkeypatch.setattr("checkwash.frontends.python.standin_installations._MAX_CONTEXT_READS", 2)
    source = b"import app.billing as billing\nbilling.total = lambda: 3\n"
    with pytest.raises(EngineError, match="context exceeds the source read limit"):
        judge({}, {"conftest.py": source}, {"tests/test_total.py": TEST})
