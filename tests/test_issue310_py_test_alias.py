"""Issue #310: `py.test` is the pytest module, and a skip spelled through it is pytest's.

The py library's `py.test` is pytest itself (py 1.11.0 maps its `test`
attribute to `pytest` and binds `sys.modules['py.test'] = pytest`). #260 read
`py.test.mark.*` decorators as pytest's marks, but a test body's skip was read
only through the module's native imports (#220), and `import py` bound
nothing: `py.test.skip()` and `py.test.xfail()` passed with zero findings,
and the same skip respelled `pytest.skip()` read as a skip added (P4; pytest
3cc58c2f78f0 does it inside a helper, #272). A name read through an import of
`py` now names pytest's object, one object under one name as
`_pytest.outcomes`' are.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.setup_skip_controls import (
    _import_pairs,
    _pytest_name,
    body_outcome,
    module_bindings,
    outcome_call,
    setup_skip_controls,
)

BILLING = b"def total(items):\n    return round(sum(items), 2)\n"
ASSERT = "assert total([50.0, 28.75]) == 78.75"


def module(imports, line=None, *, guard=None):
    """tests/test_billing.py with `line` as the first statement of its one test."""
    head = f"{imports}\nfrom app.billing import total\n\n\ndef test_total():\n"
    body = ""
    if line is not None:
        body = f"    if {guard}:\n        {line}\n" if guard else f"    {line}\n"
    return (head + body + f"    {ASSERT}\n").encode()


def judge(before, after, path="tests/test_billing.py", head=None):
    changes = [FileChange(path, "modified" if before is not None else "added", before, after)]
    snapshot = {"app/__init__.py": b"", "app/billing.py": BILLING, path: after, **(head or {})}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
                                     root_reader=snapshot.get)
    return [(f.rule, f.severity, sorted(f.deescalators), f.unit, f.message) for f in findings], verdict


def markers(source, qualname="test_total"):
    parsed = parse_python(source.encode() if isinstance(source, str) else source, collect_tests=True)
    unit = next(u for u in parsed.units if u.qualname == qualname)
    return [(m.name, m.guard) for m in unit.side.markers]


# --- The issue's rows ---------------------------------------------------------------------------

@pytest.mark.parametrize("imports,line,name", [
    ("import py", 'py.test.skip("later")', "pytest.skip"),                          # P1
    ("import py", 'py.test.xfail("later")', "pytest.xfail"),                        # P3
    ("import py", 'raise py.test.skip.Exception("later")', "pytest.skip.Exception"),
    ("import py", 'py.test.importorskip("redis")', "pytest.importorskip"),
    ("import py.test", 'py.test.skip("later")', "pytest.skip"),
    ("import py.test as t", 't.skip("later")', "pytest.skip"),
    ("import py as p", 'p.test.skip("later")', "pytest.skip"),
    ("from py import test", 'test.skip("later")', "pytest.skip"),
    ("from py.test import skip", 'skip("later")', "pytest.skip"),
    ("from py.test import xfail as x", 'x("later")', "pytest.xfail"),
], ids=["P1", "P3", "raise", "importorskip", "import_py_test", "py_test_as", "py_as", "from_py_import_test",
        "from_py_test_import", "from_py_test_import_as"])
def test_a_skip_through_py_test_disables_the_test_as_pytests_does(imports, line, name):
    hits, verdict = judge(module(imports), module(imports, line))
    assert [(rule, severity) for rule, severity, _, _, _ in hits] == [("TEST_DISABLED", "high")]
    assert hits[0][4] == f"test_total: disabling marker added ({name})"
    assert verdict == "block"


def test_the_control_spelled_with_pytest_is_unchanged():
    # P2.
    hits, verdict = judge(module("import pytest"), module("import pytest", 'pytest.skip("later")'))
    assert [(rule, severity, message) for rule, severity, _, _, message in hits] == [
        ("TEST_DISABLED", "high", "test_total: disabling marker added (pytest.skip)")]
    assert verdict == "block"


@pytest.mark.parametrize("before,after", [
    (("import py", 'py.test.skip("x")'), ("import pytest", 'pytest.skip("x")')),       # P4
    (("import pytest", 'pytest.skip("x")'), ("import py", 'py.test.skip("x")')),
    (("import py", 'py.test.xfail("x")'), ("from pytest import xfail", 'xfail("x")')),
    (("import py", 'raise py.test.skip.Exception("x")'), ("import _pytest.outcomes", "raise _pytest.outcomes.Skipped('x')")),
], ids=["P4", "back", "xfail", "raised"])
def test_a_skip_respelled_between_py_test_and_pytest_is_the_skip_it_was(before, after):
    for guard in (None, "total([]) is None"):
        hits, verdict = judge(module(*before, guard=guard), module(*after, guard=guard))
        assert hits == [] and verdict == "pass", guard


def test_a_skip_respelled_inside_a_helper_is_the_skip_it_was():
    # pytest 3cc58c2f78f0: `py.test.skip` -> `pytest.skip` inside `lsof_check`,
    # which three tests call, read as a skip added to the helper (#272).
    def source(imports, call):
        return (f"{imports}\nfrom app.billing import total\n\n\n"
                f"def lsof_check():\n    if total([]) is None:\n        {call}(\"could not run 'lsof'\")\n\n\n"
                f"def test_total():\n    lsof_check()\n    {ASSERT}\n").encode()

    hits, verdict = judge(source("import py", "py.test.skip"), source("import pytest", "pytest.skip"))
    assert hits == [] and verdict == "pass"
    # A skip added to the helper through `py.test` is reported as one through pytest is.
    plain = (b"import py\nfrom app.billing import total\n\n\ndef lsof_check():\n    return None\n\n\n"
             b"def test_total():\n    lsof_check()\n    " + ASSERT.encode() + b"\n")
    skipped = plain.replace(b"    return None\n", b"    py.test.skip('later')\n")
    hits, verdict = judge(plain, skipped)
    assert [(rule, severity, message) for rule, severity, _, _, message in hits] == [
        ("TEST_DISABLED", "high", "test_total: skip/xfail added to a helper this test calls (helper.lsof_check.skip)")]
    assert verdict == "block"


# --- Only an import of the py library is pytest ---------------------------------------------------

@pytest.mark.parametrize("imports,line", [
    ("import pytest", 'py.test.skip("later")'),                     # U1: `py` bound by nothing
    ("import py\npy = object()", 'py.test.skip("later")'),          # rebound after the import
    ("from helpers import py", 'py.test.skip("later")'),            # another module's `py`
    ("import py", 'py.skip("later")'),                              # the py library has no skip
    ("import py", 'py.testing.skip("later")'),                      # another attribute
])
def test_a_py_that_is_not_the_py_library_disables_nothing(imports, line):
    hits, verdict = judge(module(imports), module(imports, line))
    assert hits == [] and verdict == "pass"


def test_a_parameter_named_py_shadows_the_module():
    source = "import py\n\n\ndef test_total(py):\n    py.test.skip('flaky')\n    assert True\n"
    assert markers(source) == []


def test_an_import_of_py_inside_the_test_binds_as_at_module_level():
    source = "def test_total():\n    import py\n    py.test.skip('a')\n    assert True\n"
    assert markers(source) == [("pytest.skip", None)]


# --- Guards and setup read the same names ---------------------------------------------------------

def test_a_guarded_py_test_skip_is_held_by_its_compat_gate():
    imports = "import sys\nimport py"
    hits, verdict = judge(module(imports), module(imports, 'py.test.skip("posix only")', guard='sys.platform == "win32"'))
    assert [(rule, severity, de) for rule, severity, de, _, _ in hits] == [("TEST_DISABLED", "warn", ["COMPAT_GATE"])]
    assert verdict == "pass"


def test_a_py_test_skip_records_its_guard_and_its_removal_is_reported():
    imports = "import sys\nimport py"
    assert markers(module(imports, "py.test.skip('x')", guard="sys.platform == 'win32'")) == [
        ("pytest.skip", "sys.platform == 'win32'")]
    hits, verdict = judge(module(imports, "py.test.skip('x')", guard="sys.platform == 'win32'"),
                          module(imports, "py.test.skip('x')"))
    assert [(rule, severity, message) for rule, severity, _, _, message in hits] == [
        ("TEST_DISABLED", "high", "test_total: skip guard removed (was \"sys.platform == 'win32'\")")]
    assert verdict == "block"


def test_a_requested_fixture_declared_and_skipping_through_py_test_skips_its_test():
    def source(parameters):
        return ("import py\nfrom app.billing import total\n\n\n"
                "@py.test.fixture\ndef offline():\n    py.test.skip('flaky')\n\n\n"
                f"def test_total({parameters}):\n    {ASSERT}\n").encode()
    hits, verdict = judge(source(""), source("offline"))
    assert [(rule, severity, message) for rule, severity, _, _, message in hits] == [
        ("TEST_DISABLED", "high", "test_total: skip/xfail added to the setup this test runs (setup.offline.skip)")]
    assert verdict == "block"


def test_an_always_skipping_hook_through_py_test_is_a_suite_control():
    test = {"tests/test_billing.py": module("import py")}
    before = b"import py\n"
    after = b"import py\n\n\ndef pytest_runtest_setup(item):\n    py.test.skip('suite disabled')\n"
    hits, verdict = judge(before, after, path="tests/conftest.py", head=test)
    assert [(rule, severity, unit) for rule, severity, _, unit, _ in hits] == [("TEST_DISABLED", "high", "<suite>")]
    assert hits[0][4].endswith("(conftest.runtime.pytest_runtest_setup.skip)")
    assert verdict == "block"


# --- The one name ---------------------------------------------------------------------------------

def test_pytest_name_reads_py_test_as_pytest_and_nothing_else():
    assert _pytest_name("py.test") == "pytest"
    assert _pytest_name("py.test.skip") == "pytest.skip"
    assert _pytest_name("py.test.skip.Exception") == "pytest.skip.Exception"
    assert _pytest_name("py.testing.skip") == "py.testing.skip"
    assert _pytest_name("py.path.local") == "py.path.local"
    assert _pytest_name("pytest.skip") == "pytest.skip"
    assert _pytest_name("unittest.SkipTest") == "unittest.SkipTest"


def test_the_bindings_take_py_and_py_test_as_native():
    def pairs(text):
        return _import_pairs(ast.parse(text).body[0])

    assert pairs("import py") == [("py", "py")]
    assert pairs("import py.test as t") == [("t", "py.test")]
    assert pairs("from py import test") == [("test", "py.test")]
    assert pairs("from py.test import skip") == [("skip", "py.test.skip")]
    assert module_bindings(ast.parse("import py\nimport py.test as t\n")) == {"py": "py", "t": "py.test"}


def test_body_outcome_and_the_setup_proof_read_py_test_as_pytest():
    def expr(text):
        return ast.parse(text).body[0]

    assert body_outcome(expr("py.test.skip('x')").value, {"py": "py"}) == "pytest.skip"
    assert body_outcome(expr("t.xfail('x')").value, {"t": "py.test"}) == "pytest.xfail"
    assert body_outcome(expr("raise py.test.skip.Exception('x')"), {"py": "py"}) == "pytest.skip.Exception"
    # Unbound, `py` keeps its spelling, which names no outcome.
    assert body_outcome(expr("py.test.skip('x')").value, {}) is None
    assert outcome_call(expr("py.test.skip('x')").value, {"py": "py"}) == "skip"
    tree = ast.parse("import py\n\n\ndef pytest_runtest_setup(item):\n    py.test.skip('x')\n")
    assert list(setup_skip_controls(tree))
