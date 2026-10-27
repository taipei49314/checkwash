"""Class relocation needs actual closed sources, never a guessed producer.

All subject programs are bytes for static analysis; none is executed.
The original #263 control retains its original expectation and remains separate.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = "tests/test_calc.py"
PRODUCER = "app/calc.py"
APP = {"app/__init__.py": b"", PRODUCER: b"def add(a, b):\n    return a + b\n"}
PREFIX = "import pytest\nfrom app.calc import add\n\n"
MARK = 'old_python = pytest.mark.skipif("sys.version_info < (2,6)")\n\n'
BEFORE = PREFIX + "def test_one():\n    assert add(1, 2) == 3\n"
AFTER = PREFIX + MARK + "class TestAdd:\n    pytestmark = old_python\n\n    def test_one(self):\n        assert add(1, 2) == 3\n"
MOVE = {"ASSERTION_MOVED", "RESTRUCTURED", "SPLIT_OR_RENAMED", "DUPLICATE_REMAINS"}


def moved(*, before=BEFORE, after=AFTER, files=None, changes=(), reader=True, search=True, paths=True):
    snapshot = {**APP, PATH: after.encode(), **(files or {})}
    for change in changes:
        if change.after is None:
            snapshot.pop(change.path, None)
        else:
            snapshot[change.path] = change.after
    return analyze([FileChange(PATH, "modified", before.encode(), after.encode()), *changes],
                   Config(), Contract(), [], datetime.date(2026, 10, 27),
                   root_reader=snapshot.get if reader else None,
                   root_searcher=(lambda needles: search_source_mapping(snapshot, needles)) if search else None,
                   root_path_lister=(lambda: sorted(snapshot)) if paths else None,
                   root_batch_reader=(lambda selected: {path: snapshot.get(path) for path in selected}) if paths else None,
                   head_reader=snapshot.get)


def no_credit(result):
    _ir, findings, _verdict = result
    disabled = [finding for finding in findings if finding.rule == "TEST_DISABLED" and finding.unit == "test_one"]
    assert disabled
    assert all(not MOVE.intersection(finding.deescalators) for finding in disabled)


def test_closed_producer_and_inactive_string_mark_prove_plain_class_move():
    _ir, findings, verdict = moved()
    assert verdict == "pass"
    disabled = [finding for finding in findings if finding.rule == "TEST_DISABLED"]
    assert disabled and all(finding.severity == "info" and "ASSERTION_MOVED" in finding.deescalators
                            for finding in disabled)


@pytest.mark.parametrize("kwargs", [{"reader": False}, {"search": False}, {"paths": False},
                                    {"files": {PRODUCER: None}}])
def test_unknown_startup_inventory_or_producer_cannot_prove_the_original_shape(kwargs):
    no_credit(moved(**kwargs))


@pytest.mark.parametrize("after", [
    AFTER.replace("class TestAdd:", "class TestAdd(Base):"),
    AFTER.replace("class TestAdd:", "class TestAdd(metaclass=Meta):"),
    AFTER.replace("class TestAdd:", "@decorate\nclass TestAdd:"),
    AFTER.replace("    pytestmark = old_python", "    pytestmark = old_python\n    def setup_method(self):\n        touch()"),
    AFTER.replace("add(1, 2)", "add(self, 2)"),
    AFTER.replace("add(1, 2)", "self.add(1, 2)"),
    AFTER.replace("def test_one(self)", "def test_one(self, fixture)"),
    AFTER.replace("def test_one(self)", "def test_one(self=make())"),
    AFTER.replace("    pytestmark = old_python", "    pytestmark = replacement"),
    AFTER.replace("old_python = pytest.mark.skipif", "old_python = replacement.skipif"),
    AFTER.replace('"sys.version_info < (2,6)"', '"True"'),
    AFTER.replace('"sys.version_info < (2,6)"', '"sys.platform == \'win32\'"'),
    AFTER.replace('"sys.version_info < (2,6)"', '"observer()"'),
    AFTER.replace('"sys.version_info < (2,6)"', '"sys.version_info =="'),
    AFTER.replace("from app.calc import add", "from app.calc import add\nadd = replacement"),
    AFTER.replace("        assert add", "        add = replacement\n        assert add"),
])
def test_unknown_class_framework_receiver_or_binding_context_never_earns_credit(after):
    no_credit(moved(after=after))


@pytest.mark.parametrize("producer", [
    b"import inspect\ndef add(a, b):\n    return inspect.currentframe().f_back.f_locals.get('self', a)\n",
    b"def add(a):\n    return a\n",
    b"def add(a, b, c):\n    return a + b\n",
    b"def add(a, b):\n    touch()\n    return a + b\n",
])
def test_producer_call_binding_and_no_effects_are_required(producer):
    no_credit(moved(files={PRODUCER: producer}))


def test_different_pure_producers_do_not_share_a_relocation_certificate():
    no_credit(moved(changes=(FileChange(PRODUCER, "modified", APP[PRODUCER],
                                      b"def add(a, b):\n    return 3\n"),)))


@pytest.mark.parametrize("path,source", [
    ("app/__init__.py", b"import pytest\npytest.mark.skipif = replacement\n"),
    ("tests/__init__.py", b"import builtins\nbuiltins.__build_class__ = replacement\n"),
    ("pytest.py", b"mark = replacement\n"),
    ("conftest.py", b"def pytest_collection_modifyitems(items):\n    touch()\n"),
    ("tests/test_sibling.py", b"def test_sibling():\n    touch()\n"),
    ("pyproject.toml", b"[project.entry-points.pytest11]\nplugin = 'hook'\n"),
])
def test_bootstrap_plugins_and_sibling_effects_withhold_the_certificate(path, source):
    no_credit(moved(files={path: source}))


@pytest.mark.parametrize("call", ["add(1)", "add(1, 2, 3)", "add(1, a=2)",
                                 "add(1, 2, unknown=3)", "add(*(1, 2))", "add(1, **{'b': 2})"])
def test_full_call_binding_is_required_even_for_a_closed_pure_producer(call):
    no_credit(moved(before=BEFORE.replace("add(1, 2)", call), after=AFTER.replace("add(1, 2)", call)))


def test_literal_defaults_are_bound_without_running_the_producer():
    before = BEFORE.replace("add(1, 2)", "add(1)")
    after = AFTER.replace("add(1, 2)", "add(1)")
    _ir, _findings, verdict = moved(before=before, after=after,
                                   files={PRODUCER: b"def add(a, b=2):\n    return a + b\n"})
    assert verdict == "pass"


def test_invalid_source_leaves_optional_proof_empty_instead_of_raising():
    from checkwash.oracle_credit import mark_contexts

    mark_contexts(b"def broken(:\n", [], PATH, "python", source_reader=lambda path: None,
                  source_searcher=lambda needles: [], source_path_lister=lambda: [])


@pytest.mark.parametrize("condition", [
    "sys.version_info > (3,11,0) and sys.version_info < (3,12,0)",
    "sys.version_info > (3,99,0) and sys.version_info < (3,100,0)",
    "sys.version_info < (3,11,10)",
    "sys.version_info <= (3,11,9)",
    "sys.version_info < (3,12)",
    "sys.version_info < (99,)",
    "sys.version_info != (3,11)",
    "sys.version_info < (3,11,0,0)",
])
def test_sampled_false_patch_and_future_version_conditions_are_not_inactive_proofs(condition):
    no_credit(moved(after=AFTER.replace("sys.version_info < (2,6)", condition)))


@pytest.mark.parametrize("condition", [
    "sys.version_info < (2,6)", "sys.version_info <= (3,11)",
    "sys.version_info < (3,11,0)", "(3,11,0) >= sys.version_info",
])
def test_symbolically_false_supported_version_prefix_bounds_can_prove_the_gate(condition):
    _ir, _findings, verdict = moved(after=AFTER.replace("sys.version_info < (2,6)", condition))
    assert verdict == "pass"


def test_a_false_literal_subproof_does_not_bypass_independent_liveness():
    import ast

    from checkwash.oracle_class_credit import _false_marker

    assert _false_marker(ast.parse('pytest.mark.skipif("False")', mode="eval").body)
    # The ordinary marker/liveness contract remains its own admission check.
    no_credit(moved(after=AFTER.replace("sys.version_info < (2,6)", "False")))
