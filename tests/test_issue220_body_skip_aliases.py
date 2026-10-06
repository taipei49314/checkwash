"""Issue #220: a test body's skip is read through the module's import bindings.

The frontend matched four literal spellings (`pytest.skip`, `pytest.xfail`,
`pytest.importorskip`, `self.skipTest`), so `pt.skip()` after `import pytest
as pt`, or a bare `skip()` imported from pytest, passed with zero findings,
and `raise unittest.SkipTest(...)` blocked as ASSERT_REMOVED, a false reason:
the assertions are still there and the test is skipped. The body now reads
the native outcomes the setup path reads (`setup_skip_controls`), through the
same bindings, and keeps `importorskip` (220.Q1). One object has one name:
Twisted's trial exports unittest's own SkipTest, so a skip respelled between
the two is the skip the test had (scrapy bb15c93a2bbd). A `pytest_runtest_setup`
hook that always skips is read beside any import, not only `import pytest`
(J2, J3); J4 and J5 stay a named residual (220.Q2).
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
    BODY_MARKERS,
    _import_pairs,
    body_outcome,
    setup_skip_controls,
)
from checkwash.ir.markers import GUARDED_SKIP_CALLS

BILLING = b"def total(items):\n    return round(sum(items), 2)\n"
ASSERT = "assert total([50.0, 28.75]) == 78.75"


def module(imports, line=None, *, cls=False, guard=None):
    """tests/test_billing.py with `line` as the first statement of its one test."""
    if cls:
        head = f"{imports}\nfrom app.billing import total\n\n\nclass TestTotal(unittest.TestCase):\n    def test_total(self):\n"
        indent, check = "        ", "self.assertEqual(total([50.0, 28.75]), 78.75)"
    else:
        head = f"{imports}\nfrom app.billing import total\n\n\ndef test_total():\n"
        indent, check = "    ", ASSERT
    body = ""
    if line is not None:
        body = f"{indent}if {guard}:\n{indent}    {line}\n" if guard else f"{indent}{line}\n"
    return (head + body + f"{indent}{check}\n").encode()


def judge(before, after, path="tests/test_billing.py", head=None):
    changes = [FileChange(path, "modified" if before is not None else "added", before, after)]
    snapshot = {"app/__init__.py": b"", "app/billing.py": BILLING, path: after, **(head or {})}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
                                     root_reader=snapshot.get)
    return [(f.rule, f.severity, sorted(f.escalators), sorted(f.deescalators), f.unit, f.message)
            for f in findings], verdict


def markers(source, qualname="test_total"):
    parsed = parse_python(source.encode() if isinstance(source, str) else source, collect_tests=True)
    unit = next(u for u in parsed.units if u.qualname == qualname)
    return [(m.name, m.guard) for m in unit.side.markers]


@pytest.mark.parametrize("imports,line,name", [
    ("import pytest", 'pytest.skip("flaky")', "pytest.skip"),                      # B0, the control
    ("import pytest as pt", 'pt.skip("flaky")', "pytest.skip"),                     # B1
    ("from pytest import skip", 'skip("flaky")', "pytest.skip"),                    # B2
    ("from pytest import xfail", 'xfail("flaky")', "pytest.xfail"),                 # B3
    ("from pytest import skip as s", 's("flaky")', "pytest.skip"),                  # B4
    ("import unittest", 'raise unittest.SkipTest("flaky")', "unittest.SkipTest"),   # B5
    ("from unittest import SkipTest", 'raise SkipTest("flaky")', "unittest.SkipTest"),  # B6
    ("import pytest", 'raise pytest.skip.Exception("flaky")', "pytest.skip.Exception"),  # B7
    ("import pytest", 'pytest.importorskip("redis")', "pytest.importorskip"),       # B9, 220.Q1
    ("from unittest import SkipTest", "raise SkipTest", "unittest.SkipTest"),
    # One object, one name: pytest's own module, and trial's export of unittest's class.
    ("import _pytest.outcomes", '_pytest.outcomes.skip("flaky")', "pytest.skip"),
    ("from _pytest.outcomes import Skipped", 'raise Skipped("flaky")', "pytest.skip.Exception"),
    ("from unittest.case import SkipTest", 'raise SkipTest("flaky")', "unittest.SkipTest"),
    ("from twisted.trial import unittest", 'raise unittest.SkipTest("flaky")', "unittest.SkipTest"),
    ("from twisted.trial.unittest import SkipTest", 'raise SkipTest("flaky")', "unittest.SkipTest"),
    ("import twisted.trial.unittest", 'raise twisted.trial.unittest.SkipTest("flaky")', "unittest.SkipTest"),
    # A cause is evaluated first; the test is skipped or errors, never passes.
    ("import unittest", 'raise unittest.SkipTest("flaky") from None', "unittest.SkipTest"),
])
def test_a_body_skip_in_any_import_spelling_disables_the_test(imports, line, name):
    hits, verdict = judge(module(imports), module(imports, line))
    assert [(rule, severity, esc) for rule, severity, esc, _, _, _ in hits] == [
        ("TEST_DISABLED", "high", ["NO_PROD_CHANGE_IN_DIFF"])]
    assert hits[0][5] == f"test_total: disabling marker added ({name})"
    assert verdict == "block"


def test_a_raised_skip_keeps_the_assertions_it_skips():
    # B5: the raise read as a skip, not as `return`, so nothing is "removed".
    source = module("import unittest", 'raise unittest.SkipTest("flaky")').decode()
    unit = next(u for u in parse_python(source.encode(), collect_tests=True).units if u.qualname == "test_total")
    assert [a.text for a in unit.side.assertions] == [ASSERT]
    assert [m.name for m in unit.side.markers] == ["unittest.SkipTest"]
    # A raise of anything else still ends the test there.
    other = module("import unittest", 'raise RuntimeError("flaky")').decode()
    unit = next(u for u in parse_python(other.encode(), collect_tests=True).units if u.qualname == "test_total")
    assert unit.side.assertions == [] and unit.side.markers == []


def test_a_test_case_method_raises_its_skip_too():
    # B8, beside the self.skipTest control.
    for line, name in (('raise unittest.SkipTest("flaky")', "unittest.SkipTest"),
                       ('self.skipTest("flaky")', "self.skipTest")):
        hits, _ = judge(module("import unittest", cls=True), module("import unittest", line, cls=True))
        assert [(rule, severity, unit) for rule, severity, _, _, unit, _ in hits] == [
            ("TEST_DISABLED", "high", "TestTotal.test_total")], line
        assert hits[0][5].endswith(f"({name})")


@pytest.mark.parametrize("imports,line", [
    ("import pytest", 'pytest.skip("posix only")'),            # D1, the control
    ("import unittest", 'raise unittest.SkipTest("posix only")'),  # D2
    ("import pytest as pt", 'pt.skip("posix only")'),            # D3
])
def test_a_guarded_body_skip_is_held_by_its_compat_gate(imports, line):
    imports = "import sys\n" + imports
    hits, verdict = judge(module(imports), module(imports, line, guard='sys.platform == "win32"'))
    assert [(rule, severity, de) for rule, severity, _, de, _, _ in hits] == [
        ("TEST_DISABLED", "warn", ["COMPAT_GATE"])]
    assert verdict == "pass"


@pytest.mark.parametrize("imports,line", [
    ("import custom", 'custom.skip("flaky")'),                  # an unrelated module's skip
    ("from pytest import skip", 'skip = print; skip("flaky")'),  # rebound in the test
    ("import pytest\nimport custom as pytest", 'pytest.skip("flaky")'),  # the last binding wins
    ("from pytest import skip\n\n\ndef skip(reason):\n    pass", 'skip("flaky")'),  # redefined at module level
])
def test_a_name_that_is_not_pytests_skip_disables_nothing(imports, line):
    hits, verdict = judge(module(imports), module(imports, line))
    assert hits == [] and verdict == "pass"


def test_a_parameter_shadows_the_module_binding():
    source = "from pytest import skip\n\n\ndef test_total(skip):\n    skip('flaky')\n    assert True\n"
    assert markers(source) == []


def test_an_unbound_root_keeps_its_spelling():
    # Written without an import, `pytest.skip` still names pytest's skip, as
    # the literal set read it; `self.skipTest` outside a class too.
    assert markers("def test_total():\n    pytest.skip('flaky')\n    assert True\n") == [("pytest.skip", None)]
    assert markers("def test_total():\n    self.skipTest('x')\n    assert True\n") == [("self.skipTest", None)]


def test_a_raised_skip_records_its_guard():
    source = "import sys\nimport unittest\n\n\ndef test_total():\n    if sys.platform == 'win32':\n        raise unittest.SkipTest('x')\n    assert True\n"
    assert markers(source) == [("unittest.SkipTest", "sys.platform == 'win32'")]


@pytest.mark.parametrize("before,after", [
    # scrapy bb15c93a2bbd: a guarded skip respelled from trial's name to unittest's.
    (("from twisted.trial import unittest", 'raise unittest.SkipTest("no brotli")'),
     ("from unittest import SkipTest", 'raise SkipTest("no brotli")')),
    (("from unittest.case import SkipTest", 'raise SkipTest("flaky")'),
     ("import unittest", 'raise unittest.SkipTest("flaky")')),
    (("import _pytest.outcomes", '_pytest.outcomes.skip("flaky")'), ("import pytest", 'pytest.skip("flaky")')),
    (("from _pytest.outcomes import Skipped", 'raise Skipped("flaky")'),
     ("import pytest", 'raise pytest.skip.Exception("flaky")')),
])
def test_a_skip_respelled_through_the_same_object_is_the_skip_it_was(before, after):
    for guard in (None, "NO_BROTLI"):
        hits, verdict = judge(module(*before, guard=guard), module(*after, guard=guard))
        assert hits == [] and verdict == "pass", guard


def test_a_raised_skip_in_a_requested_fixture_is_read_in_trials_spelling_too():
    # The setup path reads the same table: F2's act in trial's spelling.
    def source(parameters):
        return ("import pytest\nfrom twisted.trial import unittest\nfrom app.billing import total\n\n\n"
                "@pytest.fixture\ndef offline():\n    raise unittest.SkipTest('flaky')\n\n\n"
                f"def test_total({parameters}):\n    {ASSERT}\n").encode()
    hits, verdict = judge(source(""), source("offline"))
    assert [(rule, severity, message) for rule, severity, _, _, _, message in hits] == [
        ("TEST_DISABLED", "high", "test_total: skip/xfail added to the setup this test runs (setup.offline.skip)")]
    assert verdict == "block"


def test_body_outcome_reads_calls_and_raises_through_bindings():
    bindings = {"pt": "pytest", "SkipTest": "unittest.SkipTest", "custom": None}

    def expr(text):
        return ast.parse(text).body[0]

    assert body_outcome(expr("pt.xfail('x')").value, bindings) == "pytest.xfail"
    assert body_outcome(expr("raise SkipTest('x')"), bindings) == "unittest.SkipTest"
    assert body_outcome(expr("raise SkipTest"), bindings) == "unittest.SkipTest"
    assert body_outcome(expr("custom.skip('x')").value, bindings) is None
    assert body_outcome(expr("raise"), bindings) is None
    assert body_outcome(expr("pytest.skip('x')").value, {}) == "pytest.skip"
    assert body_outcome(expr("pytest.importorskip('x')").value, {}) == "pytest.importorskip"
    # The one name of each object.
    assert body_outcome(expr("raise unittest.SkipTest"), {"unittest": "twisted.trial.unittest"}) == "unittest.SkipTest"
    assert body_outcome(expr("raise S('x')"), {"S": "unittest.case.SkipTest"}) == "unittest.SkipTest"
    assert body_outcome(expr("_pytest.outcomes.xfail('x')").value, {}) == "pytest.xfail"
    assert body_outcome(expr("raise XFailed('x')"), {"XFailed": "_pytest.outcomes.XFailed"}) == "pytest.xfail.Exception"


def test_the_guarded_names_are_the_body_markers_but_importorskip():
    # ir/markers.py cannot import the frontend; this holds the two together.
    assert GUARDED_SKIP_CALLS == BODY_MARKERS - {"pytest.importorskip"}


def test_import_pairs_bind_native_targets_or_nothing():
    def pairs(text):
        return _import_pairs(ast.parse(text).body[0])

    assert pairs("import pytest as pt, sys, os.path") == [("pt", "pytest"), ("sys", None), ("os", None)]
    assert pairs("import unittest.case") == [("unittest", "unittest")]
    assert pairs("from unittest import SkipTest as S") == [("S", "unittest.SkipTest")]
    assert pairs("from twisted.trial import unittest") == [("unittest", "twisted.trial.unittest")]
    assert pairs("from twisted.internet import defer") == [("defer", None)]
    assert pairs("from .helpers import skip") == [("skip", None)]
    assert pairs("from pytest import *") is None


HOOK_TEST = {"tests/test_billing.py": module("import pytest")}


@pytest.mark.parametrize("base,body", [
    ("import pytest", 'pytest.skip("suite disabled")'),                      # J0, the control
    ("import pytest as pt", 'pt.skip("suite disabled")'),                    # J1
    ("import sys\nimport pytest", 'pytest.skip("suite disabled")'),           # J2
    ("import unittest", 'raise unittest.SkipTest("suite disabled")'),        # J3, #199 H2's spelling
    ("import os\nfrom pytest import skip", 'skip("suite disabled")'),
])
def test_an_always_skipping_hook_is_read_beside_any_import(base, body):
    before = (base + "\n").encode()
    after = (base + f"\n\n\ndef pytest_runtest_setup(item):\n    {body}\n").encode()
    for side in (before, None):  # the hook appended, or the whole conftest added
        hits, verdict = judge(side, after, path="tests/conftest.py", head=HOOK_TEST)
        assert [(rule, severity, unit) for rule, severity, _, _, unit, _ in hits] == [
            ("TEST_DISABLED", "high", "<suite>")]
        assert hits[0][5].endswith("(conftest.runtime.pytest_runtest_setup.skip)")
        assert verdict == "block"


@pytest.mark.parametrize("source", [
    # J4 and J5 stay a named residual (220.Q2): #172's sibling narrowing.
    "import pytest\n\n\n@pytest.fixture\ndef db():\n    return {}\n",
    "import pytest\n\n\ndef pytest_addoption(parser):\n    parser.addoption('--db')\n",
    # Still no proof: a statement that runs code, and a star import.
    "import pytest\nmutate()\n",
    "import pytest\nfrom helpers import *\n",
])
def test_the_hook_proof_still_ends_at_what_it_cannot_read(source):
    tree = ast.parse(source + "\n\ndef pytest_runtest_setup(item):\n    pytest.skip('x')\n")
    assert list(setup_skip_controls(tree)) == []


def test_an_attribute_assigned_at_module_level_keeps_the_skip():
    # Only a rebinding shadows: the literal set read these, and so does the body.
    source = ("import unittest\nimport pytest\n\nunittest.TestCase.maxDiff = None\npytest.custom_flag = True\n\n\n"
              "def test_total():\n    pytest.skip('x')\n    raise unittest.SkipTest('y')\n    assert True\n")
    assert markers(source) == [("pytest.skip", None), ("unittest.SkipTest", None)]


def test_an_import_inside_the_test_binds_as_at_module_level():
    source = ("def test_total():\n    import pytest\n    from pytest import xfail as x\n    import custom as unittest\n"
              "    pytest.skip('a')\n    x('b')\n    raise unittest.SkipTest('c')\n    assert True\n")
    assert markers(source) == [("pytest.skip", None), ("pytest.xfail", None)]


@pytest.mark.parametrize("imports,line", [
    ("import pytest", 'pytest.skip("x")'),
    ("import unittest", 'raise unittest.SkipTest("x")'),
    ("import pytest as pt", 'pt.skip("x")'),
])
def test_every_spelling_keeps_the_guard_rules_of_pytest_skip(imports, line):
    # #196 183.2 and row 54 judge the guard a body skip ran under; the raised
    # and aliased spellings are judged the same way.
    imports = "import sys\n" + imports
    guarded = module(imports, line, guard='sys.platform == "win32"')
    excepted = module(imports, None).replace(
        b"def test_total():\n", f"def test_total():\n    try:\n        import numpy\n    except ImportError:\n        {line}\n".encode())
    plain = module(imports, line)
    always = module(imports, line, guard="True")
    for before, after, ending in ((guarded, plain, "skip guard removed (was 'sys.platform == \"win32\"')"),
                                  (excepted, plain, "skip guard removed (was 'except ImportError:')"),
                                  (guarded, always, "skip guard now always fires ('True')")):
        hits, verdict = judge(before, after)
        assert [(rule, severity) for rule, severity, _, _, _, _ in hits] == [("TEST_DISABLED", "high")]
        assert hits[0][5] == f"test_total: {ending}"
        assert verdict == "block"


def test_a_method_reads_its_first_parameter_as_the_instance():
    source = ("import unittest\n\n\nclass TestTotal(unittest.TestCase):\n    def test_total(this):\n"
              "        this.skipTest('x')\n        this.assertTrue(True)\n")
    assert markers(source, "TestTotal.test_total") == [("self.skipTest", None)]
    # A module-level function has no instance: its parameter is a fixture.
    assert markers("def test_total(this):\n    this.skipTest('x')\n    assert True\n") == []
