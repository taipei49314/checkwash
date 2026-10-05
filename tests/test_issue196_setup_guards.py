"""A guarded skip in a unit's setup is recorded with its guard (#196 183.2).

Ruling 196.183.2, second stage. A same-file fixture or an xunit setup callback
whose skip runs only under a condition minted no marker at all: its guard was
its justification, so the shipped default read nothing. It is now a
`setup.<provider>.<effect>` marker that carries the condition its setup
reaches it under, and it is judged as a guarded skip in a test body is. D6
qualifies an interpreter or OS gate, a guard edited to one that always holds
or removed is reported, and any other new disable is a marker added. Conftest
fixtures still read only the unconditional outcome, on the `<suite>` unit and
on the units of a changed test module that reach them (#223).
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.compat import unit_is_live
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.setup_skip_controls import fixture_setup_controls, setup_outcome

PATH = "tests/test_billing.py"
BILLING = b"def total():\n    return 78.75\n"
HEADER = "import os\nimport sys\nimport unittest\n\nimport pytest\n\nfrom app.billing import total\n\nSTRICT = True\n\n\n"
TEST = "def test_total({args}):\n    assert total() == 78.75\n"

PLATFORM = "if sys.platform == 'win32':\n    pytest.skip('posix only')\nyield"
ENVIRONMENT = "if not os.environ.get('DB'):\n    pytest.skip('no db')\nyield"
OPTIONAL = "try:\n    import numpy\nexcept ImportError:\n    pytest.skip('needs numpy')\nyield"
BARE = "pytest.skip('posix only')\nyield"


def fixture(body, name="gate"):
    lines = "".join(f"    {line}\n" if line else "\n" for line in body.split("\n"))
    return f"@pytest.fixture\ndef {name}():\n{lines}\n\n"


def module(body, args="gate", header=HEADER):
    return header + fixture(body) + TEST.format(args=args)


def guards(source):
    """Each unit's setup markers, with their guards."""
    parsed = parse_python(source.encode(), collect_tests=True)
    return {
        unit.qualname: [(m.name, m.guard) for m in unit.side.markers if m.name.startswith("setup.")]
        for unit in parsed.units
    }


def analyze_test(before, after, *extra):
    changes = [FileChange(PATH, "modified", before.encode(), after.encode()), *extra]
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 4),
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def one(before, after, *extra):
    found, verdict = analyze_test(before, after, *extra)
    assert len(found) == 1, found
    return found[0], verdict


# --- what is recorded -------------------------------------------------------

@pytest.mark.parametrize("body, guard", [
    (PLATFORM, "sys.platform == 'win32'"),
    (ENVIRONMENT, "not os.environ.get('DB')"),
    ("if os.environ.get('DB'):\n    pass\nelse:\n    pytest.skip('no db')\nyield",
     "not (os.environ.get('DB'))"),
    ("if sys.platform == 'win32':\n    pass\nelif not os.environ.get('DB'):\n    pytest.skip('no db')\nyield",
     "not (sys.platform == 'win32') and not os.environ.get('DB')"),
    ("if sys.platform != 'win32':\n    if not os.environ.get('DB'):\n        pytest.skip('no db')\nyield",
     "sys.platform != 'win32' and not os.environ.get('DB')"),
    # Code after a branch that always leaves runs only where that branch did not.
    ("if os.environ.get('DB'):\n    return\npytest.skip('no db')", "not (os.environ.get('DB'))"),
    ("if os.environ.get('DB'):\n    yield\n    return\npytest.skip('no db')", "not (os.environ.get('DB'))"),
    ("if os.environ.get('DB'):\n    raise RuntimeError('db')\npytest.skip('no db')", "not (os.environ.get('DB'))"),
    # An `except` block's condition, as a conftest's collect_ignore records it.
    ("if os.environ.get('DB'):\n    pass\nelse:\n    return\npytest.skip('no db')", "os.environ.get('DB')"),
    (OPTIONAL, 'find_spec("numpy") is None'),
    ("try:\n    import numpy\nexcept ImportError:\n    raise unittest.SkipTest('needs numpy')\nyield",
     'find_spec("numpy") is None'),
    ("try:\n    connect()\nexcept OSError:\n    pytest.skip('offline')\nyield", "except OSError"),
    ("if os.environ.get('CI'):\n    try:\n        import numpy\n    except ImportError:\n        pytest.skip('x')\nyield",
     "os.environ.get('CI') and find_spec(\"numpy\") is None"),
    # A conjunct that binds more loosely than `and` keeps its meaning.
    ("if os.environ.get('CI'):\n    if sys.platform == 'win32' or sys.platform == 'cygwin':\n        pytest.skip('x')\nyield",
     "os.environ.get('CI') and (sys.platform == 'win32' or sys.platform == 'cygwin')"),
    # Each outcome counts: the guard is the disjunction of their conditions.
    ("if sys.platform == 'win32':\n    pytest.skip('a')\nif not os.environ.get('DB'):\n    pytest.skip('b')\nyield",
     "(sys.platform == 'win32') or (not (sys.platform == 'win32') and not os.environ.get('DB'))"),
    ("if sys.platform == 'win32':\n    pytest.skip('a')\nelse:\n    pytest.skip('b')\nyield",
     "(sys.platform == 'win32') or (not (sys.platform == 'win32'))"),
    # Nothing after a statement that always ends is reached.
    ("if sys.platform == 'win32':\n    pytest.skip('a')\nelse:\n    pytest.skip('b')\n"
     "if not os.environ.get('DB'):\n    pytest.xfail('c')\nyield",
     "(sys.platform == 'win32') or (not (sys.platform == 'win32'))"),
])
def test_a_guarded_setup_skip_carries_its_condition(body, guard):
    assert guards(module(body)) == {"test_total": [("setup.gate.skip", guard)]}


def test_a_test_written_across_lines_keeps_its_parentheses():
    body = "if (\n    sys.platform == 'win32'\n    and not os.environ.get('DB')\n):\n    pytest.skip('x')\nyield"
    [(name, guard)] = guards(module(body))["test_total"]
    assert name == "setup.gate.skip"
    expected = ast.parse("sys.platform == 'win32' and not os.environ.get('DB')", mode="eval")
    assert ast.dump(ast.parse(guard, mode="eval")) == ast.dump(expected)


def test_the_guard_is_the_source_as_written():
    source = module('if sys.platform=="win32":\n    pytest.skip("posix")\nyield') + (
        "\n\nclass TestPlain:\n"
        '    def setup_method(self):\n        if sys.platform=="win32":\n            pytest.skip("posix")\n\n'
        "    def test_method(self):\n        assert total() == 78.75\n"
    )
    assert guards(source) == {
        "test_total": [("setup.gate.skip", 'sys.platform=="win32"')],
        "TestPlain.test_method": [("setup.setup_method.skip", 'sys.platform=="win32"')],
    }


def test_the_first_outcome_names_the_effect_and_is_the_evidence():
    body = "if sys.platform == 'win32':\n    pytest.xfail('a')\nif not os.environ.get('DB'):\n    pytest.skip('b')\nyield"
    parsed = parse_python(module(body).encode(), collect_tests=True)
    [marker] = parsed.units[0].side.markers
    assert (marker.name, marker.text) == ("setup.gate.xfail", "pytest.xfail('a')")


@pytest.mark.parametrize("body, marked", [
    # Every call reaches it: the marker #172 recorded, unchanged.
    (BARE, [("setup.gate.skip", None)]),
    ("if True:\n    pytest.skip('x')\nyield", [("setup.gate.skip", None)]),
    ("if sys.platform == 'win32':\n    pytest.skip('a')\npytest.xfail('b')\nyield", [("setup.gate.xfail", None)]),
    ("try:\n    import numpy\nexcept ImportError:\n    raise unittest.SkipTest('x')\npytest.skip('y')\nyield",
     [("setup.gate.skip", None)]),
    # Never reached in setup.
    ("if False:\n    pytest.skip('x')\nyield", []),
    ("yield\nif not os.environ.get('DB'):\n    pytest.skip('teardown')", []),
    ("pytest.importorskip('numpy')\nyield", []),
    # Loop, `with` and `try` bodies are not read for outcomes.
    ("for name in ('DB',):\n    if not os.environ.get(name):\n        pytest.skip('x')\nyield", []),
    ("with open(__file__):\n    pytest.skip('x')\nyield", []),
    ("try:\n    pytest.skip('x')\nexcept Exception:\n    pass\nyield", []),
    # A path that may leave without always leaving ends the reading.
    ("if os.environ.get('A'):\n    if os.environ.get('B'):\n        return\n    x = 1\npytest.skip('x')", []),
    ("try:\n    import numpy\nexcept ImportError:\n    return\npytest.skip('x')", []),
    ("for name in ():\n    return\npytest.skip('x')", []),
    ("if True:\n    if os.environ.get('A'):\n        return\npytest.skip('x')", []),
    ("if os.environ.get('A'):\n    return\nelse:\n    if os.environ.get('B'):\n        return\npytest.skip('x')", []),
    ("if os.environ.get('A'):\n    for name in ():\n        return\npytest.skip('x')", []),
    ("try:\n    import numpy\n    return\nexcept ImportError:\n    pass\npytest.skip('x')", []),
    ("try:\n    if os.environ.get('A'):\n        return\nfinally:\n    pass\npytest.skip('x')", []),
    ("value = yield\nif value:\n    pytest.skip('x')", []),
])
def test_what_every_call_reaches_or_never_reaches_is_read_as_before(body, marked):
    assert guards(module(body)) == {"test_total": marked}


def test_xunit_setup_records_its_guard():
    source = HEADER + (
        "def setup_module():\n    if sys.version_info < (3, 9):\n        pytest.skip('old')\n\n\n"
        "class TestPlain:\n"
        "    def setup_method(self):\n        if sys.platform == 'win32':\n            pytest.skip('posix')\n\n"
        "    def test_method(self):\n        assert total() == 78.75\n\n\n"
        "class TestUnit(unittest.TestCase):\n"
        "    def setUp(self):\n        if not os.environ.get('DB'):\n            self.skipTest('no db')\n\n"
        "    def test_case(self):\n        self.assertEqual(total(), 78.75)\n"
    )
    assert guards(source) == {
        "TestPlain.test_method": [
            ("setup.setup_module.skip", "sys.version_info < (3, 9)"),
            ("setup.setup_method.skip", "sys.platform == 'win32'"),
        ],
        "TestUnit.test_case": [
            ("setup.setup_module.skip", "sys.version_info < (3, 9)"),
            ("setup.setUp.skip", "not os.environ.get('DB')"),
        ],
    }


def test_a_fixture_reached_through_another_carries_its_guard():
    source = HEADER + fixture(ENVIRONMENT, "db") + fixture("return db", "session").replace(
        "def session():", "def session(db):") + TEST.format(args="session")
    assert guards(source) == {"test_total": [("setup.db.skip", "not os.environ.get('DB')")]}


def test_setup_outcome_reads_source_text_through_its_condition_reader():
    function = ast.parse("def gate():\n    if sys.platform == 'win32':\n        pytest.skip('x')\n").body[0]
    bindings = {"pytest": "pytest", "sys": None}
    effect, evidence, guard = setup_outcome(function, bindings, condition=lambda node: "WIN")
    assert (effect, guard, ast.unparse(evidence)) == ("skip", "WIN", "pytest.skip('x')")
    assert setup_outcome(function, bindings)[2] == "sys.platform == 'win32'"


def test_a_guarded_conftest_fixture_still_waits_for_its_requests():
    guarded = "import sys\n\nimport pytest\n\n\n" + fixture(PLATFORM)
    unconditional = "import pytest\n\n\n" + fixture(BARE)
    assert list(fixture_setup_controls(ast.parse(guarded))) == []
    assert [name for name, _ in fixture_setup_controls(ast.parse(unconditional))] == [
        "conftest.runtime.fixture.gate.skip"
    ]
    change = FileChange("tests/conftest.py", "modified", b"import sys\n\nimport pytest\n", guarded.encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 4))
    assert ([f for f in findings if f.rule == "TEST_DISABLED"], verdict) == ([], "pass")


# --- how it is judged -------------------------------------------------------

def test_an_interpreter_or_os_gate_newly_requested_holds_at_warn():
    finding, verdict = one(module(PLATFORM, args=""), module(PLATFORM))
    assert (finding.severity, finding.deescalators, verdict) == ("warn", ["COMPAT_GATE"], "pass")
    assert finding.message == "test_total: skip/xfail added to the setup this test runs (setup.gate.skip)"


@pytest.mark.parametrize("body", [ENVIRONMENT, OPTIONAL, "if os.environ.get('DB'):\n    return\npytest.skip('no db')"])
def test_any_other_guard_newly_requested_blocks_as_a_body_skip_does(body):
    finding, verdict = one(module(body, args=""), module(body))
    assert (finding.severity, finding.escalators, verdict) == ("high", ["NO_PROD_CHANGE_IN_DIFF"], "block")


@pytest.mark.parametrize("body, severity", [(PLATFORM, "warn"), (ENVIRONMENT, "high")])
def test_a_guarded_skip_added_to_a_requested_fixture_is_judged_by_its_guard(body, severity):
    finding, _verdict = one(module("yield"), module(body))
    assert (finding.message, finding.severity) == (
        "test_total: skip/xfail added to the setup this test runs (setup.gate.skip)", severity)


def test_a_removed_setup_guard_is_reported_with_the_guard_family_identity():
    finding, verdict = one(module(PLATFORM), module(BARE))
    assert verdict == "block"
    assert finding.severity == "high"
    assert finding.message == (
        "test_total: skip guard removed in the setup this test runs "
        "(was \"sys.platform == 'win32'\") (setup.gate.skip)"
    )
    assert finding.fingerprint == make_fingerprint("TEST_DISABLED", PATH, "test_total", "guard:setup.gate.skip")
    assert finding.after.text == "pytest.skip('posix only')"


def test_a_setup_skip_moved_out_of_its_except_block_is_a_removed_guard():
    finding, _verdict = one(module(OPTIONAL), module("pytest.skip('needs numpy')\nyield"))
    assert finding.message == (
        "test_total: skip guard removed in the setup this test runs "
        "(was 'find_spec(\"numpy\") is None') (setup.gate.skip)"
    )


@pytest.mark.parametrize("before, after, header_after, shown", [
    ("if sys.version_info < (3, 9):\n    pytest.skip('old')\nyield",
     "if sys.version_info >= (3, 0):\n    pytest.skip('old')\nyield", HEADER, "sys.version_info >= (3, 0)"),
    ("if not STRICT:\n    pytest.skip('lenient')\nyield", "if not STRICT:\n    pytest.skip('lenient')\nyield",
     HEADER.replace("STRICT = True", "STRICT = False"), "not STRICT"),
])
def test_a_setup_guard_that_now_always_holds_is_reported(before, after, header_after, shown):
    finding, verdict = one(module(before), module(after, header=header_after))
    assert verdict == "block"
    assert finding.message == (
        f"test_total: skip guard in the setup this test runs now always fires ({shown!r}) (setup.gate.skip)"
    )
    assert finding.fingerprint == make_fingerprint("TEST_DISABLED", PATH, "test_total", "guard:setup.gate.skip")


def test_two_branches_that_cover_every_run_earn_no_gate():
    body = "if sys.platform == 'win32':\n    pytest.skip('a')\nelse:\n    pytest.skip('b')\nyield"
    finding, verdict = one(module(body, args=""), module(body))
    assert (finding.severity, finding.deescalators, verdict) == ("high", [], "block")


def test_an_unchanged_guarded_setup_is_quiet():
    assert analyze_test(module(ENVIRONMENT), module(ENVIRONMENT).replace("78.75", "78.75  # same")) == ([], "pass")


def test_a_new_test_requesting_a_guarded_fixture_is_not_a_disable():
    before = module(ENVIRONMENT, args="")
    after = before + "\n\n" + TEST.format(args="gate").replace("test_total", "test_total_again")
    assert analyze_test(before, after) == ([], "pass")


def test_a_removed_setup_guard_beside_a_production_change_holds_at_warn():
    repair = FileChange("app/billing.py", "modified", BILLING, b"def total():\n    return round(78.75, 2)\n")
    finding, verdict = one(module(PLATFORM), module(BARE), repair)
    assert (finding.severity, finding.deescalators, verdict) == ("warn", ["REPAIR_EVIDENCE"], "pass")


def test_xunit_guard_removal_names_the_callback():
    before = HEADER + (
        "class TestTotal:\n"
        "    def setup_method(self):\n        if sys.platform == 'win32':\n            pytest.skip('posix')\n\n"
        "    def test_total(self):\n        assert total() == 78.75\n"
    )
    after = before.replace("        if sys.platform == 'win32':\n            pytest.skip('posix')\n",
                           "        pytest.skip('posix')\n")
    finding, _verdict = one(before, after)
    assert finding.message == (
        "TestTotal.test_total: skip guard removed in the setup this test runs "
        "(was \"sys.platform == 'win32'\") (setup.setup_method.skip)"
    )


@pytest.mark.parametrize("body, live", [(PLATFORM, True), (ENVIRONMENT, False), (BARE, False)])
def test_liveness_reads_a_setup_guard_as_it_reads_a_body_guard(body, live):
    parsed = parse_python(module(body).encode(), collect_tests=True)
    assert unit_is_live(parsed.units[0].side, {}) is live


def test_an_os_gate_in_setup_lends_nothing_to_another_disable():
    # D6 judges the marker a finding reports (#208): the setup gate holds only
    # its own finding, so a new unconditional skip on the same test blocks.
    after = module(PLATFORM).replace("def test_total", "@pytest.mark.skip(reason='flaky')\ndef test_total")
    finding, verdict = one(module(PLATFORM), after)
    assert (finding.message, finding.deescalators, verdict) == (
        "test_total: disabling marker added (pytest.mark.skip)", [], "block")
