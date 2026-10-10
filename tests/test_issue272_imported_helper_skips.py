"""A skip a test reaches through a helper it imports from another module is read (#272, second stage).

The first stage read a skip a test reaches through a same-file helper. A test
that imports the helper instead, `from tests.helpers import offline`, and calls
`offline()` was skipped as surely, and passed with zero findings (the issue's
H5).

Ruling 272.Q2 (a): follow the import into the head tree, as #223 follows the
conftest chain. The module is the one an imported assertion helper resolves
to: a dotted module from the repository root, a dotless one beside the test.
It is read as the conftest chain is: a file the diff changes on its own side,
any other once from the strict head snapshot, within the chain's limits, and
only when it is a test or conftest module. #357 extends D-124 reading 1 to
guarded outcomes closed over the helper module's names. The marker is
`helper.<function>.<effect>` (272.Q3), with the helper file's text and span.
"""
import datetime

import pytest

from checkwash import engine
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.change import EngineError
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.helper_skips import Foreign, HelperModule, imported_helper_names
from checkwash.report.context import ReportContext

TODAY = datetime.date(2026, 10, 7)
APP = {"app/__init__.py": b"", "app/billing.py": b"def total(items):\n    return round(sum(items), 2)\n"}
HELPERS = (
    "import os\n\nimport pytest\n\nNET = os.environ.get('NET')\n\n\n"
    "def offline():\n    pytest.skip('flaky')\n\n\n"
    "def maybe():\n    if not NET:\n        pytest.skip('no net')\n\n\n"
    "def broken():\n    pytest.xfail('broken')\n\n\n"
    "def outer():\n    _inner()\n\n\n"
    "def _inner():\n    raise pytest.skip.Exception('inner')\n\n\n"
    "later = lambda: pytest.skip('later')\n\n\n"
    "def chained():\n    from tests.more import elsewhere\n    elsewhere()\n\n\n"
    "def rows():\n    pytest.skip('never runs')\n    yield 1\n"
)
SNAPSHOT = {**APP, "tests/__init__.py": b"", "tests/helpers.py": HELPERS.encode()}
MODULE = "import sys\n\nimport pytest\n\nfrom app.billing import total\n{imports}\n\n\n{defs}"
TEST = "def test_total():\n    {call}\n    assert total([30, 48.75]) == 78.75\n"
BASE = MODULE.format(imports="", defs=TEST.format(call="pass"))


def module(call, imports="from tests.helpers import offline", defs=""):
    return MODULE.format(imports=imports, defs=defs + TEST.format(call=call))


def outcome(before, after, snapshot=SNAPSHOT, path="tests/test_x.py", extra=(), report=None):
    changes = [FileChange(path, "modified", before.encode(), after.encode()), *extra]
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY,
        head_reader=snapshot.get, root_reader=snapshot.get, report_context=report,
    )
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


def disabled(name, severity="high"):
    return ("TEST_DISABLED", severity, f"skip/xfail added to a helper this test calls ({name})")


def markers(source, resolve, qualname="test_total"):
    parsed = parse_python(source.encode(), collect_tests=True, imported=resolve)
    [unit] = [u for u in parsed.units if u.qualname == qualname]
    return [(m.name, m.text, m.guard) for m in unit.side.markers]


def helpers_module(module_name, original):
    return HelperModule(HELPERS.encode(), "tests/helpers.py").outcomes(original) if module_name == "tests.helpers" else ()


# --- the issue's row, and how the import is written ------------------------------------------

@pytest.mark.parametrize("imports, call", [
    # H5: a dotted module, from the repository root
    ("from tests.helpers import offline", "offline()"),
    # a dotless module beside the test
    ("from helpers import offline", "offline()"),
    # the same module, package-relative
    ("from .helpers import offline", "offline()"),
    # an alias calls the same function
    ("from tests.helpers import offline as off", "off()"),
], ids=["dotted", "sibling", "relative", "alias"])
def test_a_skip_in_an_imported_helper_is_reported_as_a_same_file_helpers_is(imports, call):
    assert outcome(BASE, module(call, imports)) == ("block", [disabled("helper.offline.skip")])


def test_the_same_helper_in_the_test_module_is_the_contrast():
    defs = "def offline():\n    pytest.skip('flaky')\n\n\n"
    assert outcome(BASE, module("offline()", imports="", defs=defs)) == ("block", [disabled("helper.offline.skip")])


@pytest.mark.parametrize("call, name", [
    ("broken()", "helper.broken.xfail"),
    # a helper the imported one calls in its own module, named for the one that holds the outcome
    ("outer()", "helper._inner.skip"),
    # a lambda the module binds to a name
    ("later()", "helper.later.skip"),
], ids=["xfail", "its_own_helper", "lambda"])
def test_what_the_imported_helper_reaches_in_its_module_is_read(call, name):
    imports = f"from tests.helpers import {call[:-2]}"
    assert outcome(BASE, module(call, imports)) == ("block", [disabled(name)])


def test_the_marker_keeps_the_helper_files_text_and_span():
    parsed = parse_python(module("offline()").encode(), collect_tests=True, imported=helpers_module)
    [marker] = parsed.units[0].side.markers
    assert (marker.name, marker.text) == ("helper.offline.skip", "pytest.skip('flaky')")
    assert HELPERS[marker.span[0]:marker.span[1]] == "pytest.skip('flaky')"
    assert parsed.marker_origins == {(marker.name, marker.span, marker.text): "tests/helpers.py"}


def test_a_report_locates_the_finding_in_the_helper_file():
    report = ReportContext(collect_locations=True)
    outcome(BASE, module("offline()"), report=report)
    parsed = parse_python(module("offline()").encode(), collect_tests=True, imported=helpers_module)
    [marker] = parsed.units[0].side.markers
    line = HELPERS[:marker.span[0]].count("\n") + 1
    assert report.location("tests/test_x.py", marker) == ("tests/helpers.py", line)


# --- what is not read --------------------------------------------------------------------------

def test_a_guarded_skip_in_the_imported_helper_is_read():
    """#357's explicit ruling moves this unit-test pin to the closed guard."""
    assert outcome(BASE, module("maybe()", "from tests.helpers import maybe")) == (
        "block", [disabled("helper.maybe.skip")])


@pytest.mark.parametrize("call, imports", [
    # a helper imported into the helper module is not followed: one hop into the tree
    ("chained()", "from tests.helpers import chained"),
    # a generator's body does not run when it is called
    ("rows()", "from tests.helpers import rows"),
    # an attribute call is no call by a plain name
    ("helpers.offline()", "from tests import helpers"),
], ids=["second_hop", "generator", "attribute_call"])
def test_what_the_reading_does_not_follow(call, imports):
    snapshot = {**SNAPSHOT, "tests/more.py": b"import pytest\n\n\ndef elsewhere():\n    pytest.skip('x')\n"}
    assert outcome(BASE, module(call, imports), snapshot=snapshot) == ("pass", [])


def test_a_production_module_is_not_read():
    """Only a test or conftest module is: an imported assertion helper's module is read the same way."""
    snapshot = {**APP, "app/testing.py": HELPERS.encode()}
    assert outcome(BASE, module("offline()", "from app.testing import offline"), snapshot=snapshot) == ("pass", [])


@pytest.mark.parametrize("snapshot", [
    {**APP},
    {**APP, "tests/helpers.py": b"def offline(:\n    pytest.skip('x')\n"},
], ids=["absent", "unparseable"])
def test_a_module_that_cannot_be_read_records_nothing(snapshot):
    assert outcome(BASE, module("offline()"), snapshot=snapshot) == ("pass", [])


@pytest.mark.parametrize("defs, call", [
    # a parameter of the same name is a fixture's value, not the function
    ("", "pass"),
    # a module-level binding after the import rebinds the name
    ("offline = print\n\n\n", "offline()"),
], ids=["parameter", "rebound"])
def test_a_name_bound_another_way_is_not_the_imported_function(defs, call):
    test = (MODULE.format(imports="from tests.helpers import offline", defs=defs)
            + "def test_total(offline):\n    offline()\n    assert total([30, 48.75]) == 78.75\n"
            if call == "pass" else module(call, defs=defs))
    assert outcome(BASE, test) == ("pass", [])


def test_a_star_import_may_rebind_any_name():
    source = module("offline()", imports="from tests.helpers import offline\nfrom tests.more import *")
    assert imported_helper_names(__import__("ast").parse(source)) == {}


def test_a_module_that_spells_no_outcome_is_not_parsed():
    helper = HelperModule(b"def offline(:\n    return None\n", "tests/helpers.py")
    assert helper.outcomes("offline") == ()


# --- guards at the call site, and what the base already reached -------------------------------

def test_a_platform_gate_at_the_call_site_is_judged_as_the_same_gate_in_the_body():
    after = module("if sys.platform == 'win32':\n        offline()")
    assert outcome(BASE, after) == ("pass", [disabled("helper.offline.skip", "warn")])


def test_the_call_sites_condition_is_the_markers_guard():
    after = module("if sys.platform == 'win32':\n        offline()")
    assert markers(after, helpers_module) == [("helper.offline.skip", "pytest.skip('flaky')", "sys.platform == 'win32'")]


def test_a_test_that_already_called_the_helper_is_no_event():
    before = module("offline()")
    after = before.replace("78.75\n", "78.75  # checked\n")
    assert outcome(before, after) == ("pass", [])


def test_a_skip_added_to_an_imported_helper_the_diff_also_changes_is_read_on_each_side():
    before = module("offline()")
    after = before + "\n"
    old = b"import pytest\n\n\ndef offline():\n    return None\n"
    helpers = FileChange("tests/helpers.py", "modified", old, HELPERS.encode())
    assert outcome(before, after, extra=[helpers]) == ("block", [disabled("helper.offline.skip")])


def test_a_skip_moved_from_the_body_into_an_imported_helper_is_the_skip_it_was():
    before = MODULE.format(imports="", defs=TEST.format(call="pytest.skip('flaky')"))
    after = module("offline()")
    assert outcome(before, after) == ("pass", [])


def test_a_same_file_helper_that_calls_the_imported_one_reaches_its_skip():
    defs = "def _wrapped():\n    offline()\n\n\n"
    assert outcome(BASE, module("_wrapped()", defs=defs)) == ("block", [disabled("helper.offline.skip")])


# --- setup ------------------------------------------------------------------------------------

@pytest.mark.parametrize("defs, test, qualname", [
    ("@pytest.fixture\ndef items():\n    offline()\n    return [30, 48.75]\n\n\n",
     "def test_total(items):\n    assert total(items) == 78.75\n", "test_total"),
    ("def setup_function():\n    offline()\n\n\n",
     "def test_total():\n    assert total([30, 48.75]) == 78.75\n", "test_total"),
    ("", "class TestTotal:\n    def setup_method(self):\n        offline()\n\n"
         "    def test_total(self):\n        assert total([30, 48.75]) == 78.75\n", "TestTotal.test_total"),
], ids=["fixture", "setup_function", "setup_method"])
def test_setup_that_calls_an_imported_helper_reaches_its_skip(defs, test, qualname):
    source = MODULE.format(imports="from tests.helpers import offline", defs=defs) + test
    assert [m[0] for m in markers(source, helpers_module, qualname)] == ["helper.offline.skip"]


# --- reads ------------------------------------------------------------------------------------

def test_each_module_is_read_once_for_every_test_module_and_side(monkeypatch):
    """A module the diff does not change is the same on both sides: one read serves both."""
    read = []

    def counted(data, path):
        read.append(path)
        return HelperModule(data, path)

    monkeypatch.setattr(engine, "HelperModule", counted)
    x, y = module("offline()"), module("offline()").replace("test_total", "test_other")
    changes = [
        FileChange("tests/test_x.py", "modified", x.encode(), (x + "\n").encode()),
        FileChange("tests/test_y.py", "modified", y.encode(), (y + "\n").encode()),
    ]
    _ir, findings, _verdict = analyze(
        changes, Config(), Contract(), [], TODAY, head_reader=SNAPSHOT.get, root_reader=SNAPSHOT.get
    )
    assert read == ["tests/helpers.py"]
    assert findings == []


def test_reads_past_the_chain_limit_are_an_engine_error(monkeypatch):
    """The conftest chain's two levels fit; the helper module is one read past the limit."""
    monkeypatch.setattr(engine, "_MAX_CHAIN_READS", 2)
    with pytest.raises(EngineError, match="imported helper modules exceed the source read limit"):
        outcome(BASE, module("offline()"))


def test_the_foreign_evidence_names_the_file():
    [(helper, effect, evidence, conds)] = HelperModule(HELPERS.encode(), "tests/helpers.py").outcomes("offline")
    assert (helper, effect, conds) == ("offline", "skip", ())
    assert evidence == Foreign("pytest.skip('flaky')", evidence.span, "tests/helpers.py")


# --- a D10 survivor ---------------------------------------------------------------------------

def test_a_survivor_whose_setup_calls_an_imported_skipping_helper_is_not_live():
    """D10 reads a survivor's own setup, now with the helpers it imports, as #266 reads its conftest chain."""
    body = "def test_total():\n    assert total() == 78.75\n"
    other = "\n\ndef test_other():\n    assert total() > 0\n"
    head = {
        **{p: d.decode() for p, d in SNAPSHOT.items()},
        "tests/test_copy.py": ("from app.billing import total\nfrom tests.helpers import offline\n\n\n"
                               "def setup_function():\n    offline()\n\n\n" + body),
    }
    before = "from app.billing import total\n\n\n" + body + other
    after = "from app.billing import total\n\n\n" + other.lstrip("\n")
    files = {p: d.encode() for p, d in head.items()}
    snapshot = {**files, "tests/test_billing.py": after.encode()}
    _ir, findings, verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], TODAY,
        head_reader=files.get,
        head_searcher=lambda needles: [p for p, d in sorted(files.items()) if any(n.encode() in d for n in needles)],
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    assert (verdict, [(f.unit, f.severity, f.deescalators) for f in findings if f.rule == "TEST_DISABLED"]) == (
        "block", [("test_total", "high", [])])
