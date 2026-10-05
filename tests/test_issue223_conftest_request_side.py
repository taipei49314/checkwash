"""A test that starts requesting an always-skip conftest fixture is reported (#223).

pytest resolves the fixtures a test requests through its own module, its
classes and every `conftest.py` above it. checkwash resolved only the
module and its classes, so an existing test that started requesting an
existing conftest fixture whose setup always skips passed with no finding:
by parameter, by `usefixtures`, through a `pytestmark`, or through a
same-file fixture. The same request of a same-file skip fixture blocked.

223.Q1: when one diff both adds the conftest fixture and makes a test request
it, both findings are reported: the conftest's `<suite>` control and the
unit's `setup.*` marker.

223.Q2: the chain is every `conftest.py` from the test file's directory up
to the repository root, on each side. The nearest definition of a name wins,
and the test module's own wins over all of them. `pytest_plugins` fixtures
stay a residual (THREATMODEL row 104).
"""
import datetime

import pytest

import checkwash.engine as engine
from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint
from checkwash.frontends.python.frontend import parse_conftest_level, parse_python
from checkwash.report.context import ReportContext

TEST = "tests/test_billing.py"
TODAY = datetime.date(2026, 10, 5)
APP = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
SKIP = (
    "import pytest\n\n\n@pytest.fixture\ndef db():\n    return {}\n\n\n"
    '@pytest.fixture\ndef needs_network():\n    pytest.skip("network tests are disabled")\n'
)
PLAIN = "import pytest\n\n\n@pytest.fixture\ndef needs_network():\n    return None\n"
ADDED = "test_total: skip/xfail added to the setup this test runs (setup.needs_network.skip)"


def module(signature="def test_total():", prelude="", body="    assert total() == 78.75\n"):
    return f"import pytest\n\nfrom app.billing import total\n{prelude}\n\n{signature}\n{body}"


BEFORE = module()


def run(after, conftests=None, before=BEFORE, others=(), path=TEST, old_path=None, report=None, reader=True):
    """TEST_DISABLED (unit, message, severity) for one test module edit, and the verdict."""
    files = {**APP, **({"tests/conftest.py": SKIP} if conftests is None else conftests)}
    snapshot = {name: data.encode() if isinstance(data, str) else data for name, data in files.items()}
    changes = [FileChange(path, "modified", before.encode(), after.encode(), old_path=old_path), *others]
    for change in changes:
        if change.after is not None:
            snapshot[change.path] = change.after
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY, head_reader=snapshot.get,
        root_reader=snapshot.get if reader else None, report_context=report,
    )
    return [(f.unit, f.message, f.severity) for f in findings if f.rule == "TEST_DISABLED"], verdict


def blocks(*rows):
    return [(unit, message, "high") for unit, message in rows], "block"


# --- the conftest's own reading -------------------------------------------------------------


def test_a_level_keeps_only_unconditional_outcomes():
    source = SKIP + (
        "\n\n@pytest.fixture\ndef gated():\n    if not os.environ.get('NETWORK'):\n        pytest.skip('off')\n"
        "\n\n@pytest.fixture(autouse=True)\ndef flaky():\n    pytest.xfail('backend is flaky')\n"
    )
    level = parse_conftest_level(source.encode(), "tests/conftest.py")
    assert level.path == "tests/conftest.py"
    assert level.fixtures["db"] == (frozenset(), False, None)
    assert level.fixtures["gated"][2] is None
    effect, (text, span), guard = level.fixtures["needs_network"][2]
    assert (effect, text, guard) == ("skip", 'pytest.skip("network tests are disabled")', None)
    assert source[span[0]:span[1]] == text
    assert level.fixtures["flaky"][1] is True and level.fixtures["flaky"][2][0] == "xfail"


def test_a_level_marks_what_it_cannot_see():
    source = (
        "import os\nimport pytest\nfrom helpers import client\nfrom more import *\n\n"
        "token = make_token()\n\n\n@other.fixture\ndef server():\n    return 1\n\n\n"
        "if os.name == 'nt':\n    @pytest.fixture\n    def windows():\n        pytest.skip('posix only')\n\n\n"
        "def helper():\n    return 1\n\n\nclass Base:\n    pass\n\n\n"
        "@pytest.fixture\ndef plain():\n    return 1\n"
    )
    level = parse_conftest_level(source.encode(), "conftest.py")
    assert {"os", "pytest", "client", "token", "server", "windows"} <= level.opaque
    assert not {"helper", "Base", "plain"} & level.opaque
    assert level.star is True
    assert parse_conftest_level(b"import pytest\n", "conftest.py").star is False


def test_a_conftest_that_does_not_parse_is_no_level():
    assert parse_conftest_level(b"def (:\n", "tests/conftest.py") is None


def test_the_module_reads_the_chain_only_when_given():
    level = parse_conftest_level(SKIP.encode(), "tests/conftest.py")
    source = module("def test_total(needs_network):").encode()
    assert [m.name for m in parse_python(source, collect_tests=True).units[0].side.markers] == []
    parsed = parse_python(source, collect_tests=True, chain=(level,))
    (marker,) = parsed.units[0].side.markers
    assert (marker.name, marker.text, marker.guard) == (
        "setup.needs_network.skip", 'pytest.skip("network tests are disabled")', None)
    assert parsed.marker_origins == {(marker.name, marker.span, marker.text): "tests/conftest.py"}


# --- every way a test requests the fixture (S1-S6) ------------------------------------------


@pytest.mark.parametrize("after", [
    module("def test_total(needs_network):"),
    module('@pytest.mark.usefixtures("needs_network")\ndef test_total():'),
    module(prelude='\npytestmark = pytest.mark.usefixtures("needs_network")'),
    module("def test_total(client):", prelude="\n\n@pytest.fixture\ndef client(needs_network):\n    return object()"),
    module("def test_total(client):", prelude="\n\n@pytest.fixture\ndef client(request, needs_network):\n    return 1"),
], ids=["parameter", "usefixtures", "pytestmark", "same-file-fixture", "fixture-with-request"])
def test_each_request_reaches_the_conftest_fixture(after):
    assert run(after) == blocks(("test_total", ADDED))


@pytest.mark.parametrize("decorator", [
    '@pytest.mark.usefixtures("needs_network")\nclass TestBilling:',
    'class TestBilling:\n    pytestmark = pytest.mark.usefixtures("needs_network")\n',
])
def test_a_class_request_reaches_its_methods(decorator):
    before = module("class TestBilling:", body="    def test_total(self):\n        assert total() == 78.75\n")
    after = module(decorator, body="    def test_total(self):\n        assert total() == 78.75\n")
    assert run(after, before=before) == blocks(
        ("TestBilling.test_total",
         "TestBilling.test_total: skip/xfail added to the setup this test runs (setup.needs_network.skip)"))


def test_a_unittest_class_with_usefixtures():
    before = (
        "import unittest\n\nimport pytest\n\nfrom app.billing import total\n\n\n"
        "class BillingTest(unittest.TestCase):\n    def test_total(self):\n        self.assertEqual(total(), 78.75)\n"
    )
    after = before.replace("class BillingTest", '@pytest.mark.usefixtures("needs_network")\nclass BillingTest')
    assert run(after, before=before) == blocks(
        ("BillingTest.test_total",
         "BillingTest.test_total: skip/xfail added to the setup this test runs (setup.needs_network.skip)"))


@pytest.mark.parametrize("where", ["conftest.py", "tests/conftest.py"])
def test_the_chain_runs_to_the_repository_root(where):
    path = "tests/unit/billing/test_billing.py"
    assert run(module("def test_total(needs_network):"), {where: SKIP}, path=path) == blocks(("test_total", ADDED))


def test_a_plain_conftest_fixture_is_no_event():
    assert run(module("def test_total(db):")) == ([], "pass")


def test_a_guarded_conftest_skip_waits_for_183_2():
    gated = (
        "import os\n\nimport pytest\n\n\n@pytest.fixture\ndef needs_network():\n"
        '    if not os.environ.get("NETWORK"):\n        pytest.skip("network tests are disabled")\n'
    )
    assert run(module("def test_total(needs_network):"), {"tests/conftest.py": gated}) == ([], "pass")


def test_an_xfail_fixture():
    flaky = 'import pytest\n\n\n@pytest.fixture\ndef flaky_backend():\n    pytest.xfail("backend is flaky")\n'
    assert run(module("def test_total(flaky_backend):"), {"tests/conftest.py": flaky}) == blocks(
        ("test_total", "test_total: skip/xfail added to the setup this test runs (setup.flaky_backend.xfail)"))


def test_a_request_removed_is_no_event():
    assert run(BEFORE, before=module("def test_total(needs_network):")) == ([], "pass")


# --- which definition a request reaches -----------------------------------------------------


def test_the_test_modules_own_fixture_wins():
    after = module("def test_total(needs_network):",
                   prelude="\n\n@pytest.fixture\ndef needs_network():\n    return None")
    assert run(after) == ([], "pass")


@pytest.mark.parametrize("module_body, class_body, expected", [
    ('    pytest.skip("off")', "        return None", ([], "pass")),
    ("    return None", '        pytest.skip("off")', blocks((
        "TestBilling.test_total",
        "TestBilling.test_total: skip/xfail added to the setup this test runs (setup.needs_network.skip)"))),
])
def test_a_class_fixture_wins_over_the_modules(module_body, class_body, expected):
    """Nearest first: the innermost class, then the module, then each conftest."""
    def source(signature):
        return module(
            "class TestBilling:",
            prelude=f"\n\n@pytest.fixture\ndef needs_network():\n{module_body}",
            body=(f"    @pytest.fixture\n    def needs_network(self):\n{class_body}\n\n"
                  f"    {signature}\n        assert total() == 78.75\n"),
        )
    assert run(source("def test_total(self, needs_network):"), {}, before=source("def test_total(self):")) == expected


def test_the_nearest_conftest_wins():
    after = module("def test_total(needs_network):")
    assert run(after, {"conftest.py": SKIP, "tests/conftest.py": PLAIN}) == ([], "pass")
    assert run(after, {"conftest.py": PLAIN, "tests/conftest.py": SKIP}) == blocks(("test_total", ADDED))


@pytest.mark.parametrize("prelude", [
    "from tests.helpers import needs_network",
    "from tests.helpers import *",
    "needs_network = make_fixture()",
    "\n\n@helpers.fixture\ndef needs_network():\n    return None",
])
def test_a_name_the_module_binds_otherwise_stops_the_request(prelude):
    assert run(module("def test_total(needs_network):", prelude="\n" + prelude)) == ([], "pass")


@pytest.mark.parametrize("nearer", ["from tests.fixtures import *\n", "from tests.fixtures import needs_network\n"])
def test_a_name_a_nearer_conftest_binds_otherwise_stops_the_request(nearer):
    after = module("def test_total(needs_network):")
    assert run(after, {"conftest.py": SKIP, "tests/conftest.py": nearer}) == ([], "pass")


def test_a_plain_def_or_class_of_the_name_does_not_stop_it():
    after = module("def test_total(needs_network):", prelude="\n\ndef needs_network():\n    return None")
    assert run(after) == blocks(("test_total", ADDED))


def test_a_fixture_that_requests_its_own_name_reaches_the_next_definition():
    wrapper = "\n\n@pytest.fixture\ndef needs_network(needs_network):\n    return needs_network"
    assert run(module("def test_total(needs_network):", prelude=wrapper)) == blocks(("test_total", ADDED))
    nearer = "import pytest\n\n\n@pytest.fixture\ndef needs_network(needs_network):\n    return needs_network\n"
    after = module("def test_total(needs_network):")
    assert run(after, {"conftest.py": SKIP, "tests/conftest.py": nearer}) == blocks(("test_total", ADDED))


def test_a_conftest_fixture_reaches_the_test_modules_fixture():
    """pytest resolves every name in the closure as the test sees it."""
    client = "import pytest\n\n\n@pytest.fixture\ndef client(backend):\n    return backend\n"
    backend = '\n\n@pytest.fixture\ndef backend():\n    pytest.skip("no backend")'
    before = module(prelude=backend)
    after = module("def test_total(client):", prelude=backend)
    assert run(after, {"tests/conftest.py": client}, before=before) == blocks(
        ("test_total", "test_total: skip/xfail added to the setup this test runs (setup.backend.skip)"))


def test_a_directly_parametrized_name_runs_no_fixture():
    after = module('@pytest.mark.parametrize("needs_network", [1])\ndef test_total(needs_network):')
    assert run(after) == ([], "pass")


def test_an_autouse_conftest_skip_reaches_a_test_moved_below_it():
    parked = 'import pytest\n\n\n@pytest.fixture(autouse=True)\ndef off():\n    pytest.skip("parked")\n'
    moved = FileChange("tests/parked/test_billing.py", "added", None, BEFORE.encode())
    gone = FileChange(TEST, "deleted", BEFORE.encode(), None)
    _ir, findings, verdict = analyze(
        [gone, moved], Config(), Contract(), [], TODAY,
        root_reader={**APP, "tests/parked/conftest.py": parked.encode(),
                     "tests/parked/test_billing.py": BEFORE.encode()}.get,
    )
    assert [(f.unit, f.message) for f in findings if f.rule == "TEST_DISABLED"] == [
        ("test_total", "test_total: test unit disappeared")]
    assert verdict == "block"


def test_an_unchanged_autouse_conftest_skip_is_no_event():
    parked = 'import pytest\n\n\n@pytest.fixture(autouse=True)\ndef off():\n    pytest.skip("parked")\n'
    assert run(BEFORE.replace("78.75\n", "78.75  # same\n"), {"tests/conftest.py": parked}) == ([], "pass")


def test_a_rename_reads_the_base_side_below_its_old_path():
    after = module("def test_total(needs_network):")
    assert run(after, {"tests/legacy/conftest.py": PLAIN, "tests/conftest.py": SKIP},
               before=after, old_path="tests/legacy/test_billing.py") == blocks(("test_total", ADDED))


# --- 223.Q1 ---------------------------------------------------------------------------------


def test_adding_the_fixture_and_requesting_it_reports_both():
    conftest = FileChange("tests/conftest.py", "modified", PLAIN.replace("needs_network", "db").encode(),
                          SKIP.encode())
    rows, verdict = run(module("def test_total(needs_network):"), {}, others=[conftest])
    assert rows == [
        ("<suite>", "<suite>: conftest fixture setup now ends every requesting test in skip/xfail "
                    "(conftest.runtime.fixture.needs_network.skip)", "high"),
        ("test_total", ADDED, "high"),
    ]
    assert verdict == "block"


def test_moving_the_skip_fixture_from_the_module_to_conftest_keeps_the_unit():
    """The unit ran the same skip on both sides; the conftest now holds it (183.1 (a))."""
    fixture = '\n\n@pytest.fixture\ndef needs_network():\n    pytest.skip("network tests are disabled")'
    conftest = FileChange("tests/conftest.py", "modified", PLAIN.replace("needs_network", "db").encode(),
                          SKIP.encode())
    rows, _verdict = run(module("def test_total(needs_network):"), {},
                         before=module("def test_total(needs_network):", prelude=fixture), others=[conftest])
    assert [unit for unit, _message, _severity in rows] == ["<suite>"]


def test_the_fingerprint_is_the_setup_markers():
    """A skip fixture in the module or in a conftest is one marker: an exemption covers both."""
    rows, _verdict = run(module("def test_total(needs_network):"))
    assert rows
    _ir, findings, _verdict = analyze(
        [FileChange(TEST, "modified", BEFORE.encode(), module(
            "def test_total(needs_network):",
            prelude='\n\n@pytest.fixture\ndef needs_network():\n    pytest.skip("x")').encode())],
        Config(), Contract(), [], TODAY,
    )
    same_file = [f.fingerprint for f in findings if f.rule == "TEST_DISABLED"]
    snapshot = {**APP, "tests/conftest.py": SKIP.encode()}
    _ir, findings, _verdict = analyze(
        [FileChange(TEST, "modified", BEFORE.encode(), module("def test_total(needs_network):").encode())],
        Config(), Contract(), [], TODAY, root_reader=snapshot.get,
    )
    conftest = [f.fingerprint for f in findings if f.rule == "TEST_DISABLED"]
    expected = make_fingerprint("TEST_DISABLED", TEST, "test_total", "setup.needs_network.skip")
    assert same_file == conftest == [expected]


def test_the_report_locates_the_conftest_line():
    report = ReportContext(collect_locations=True)
    snapshot = {**APP, "tests/conftest.py": SKIP.encode()}
    _ir, findings, _verdict = analyze(
        [FileChange(TEST, "modified", BEFORE.encode(), module("def test_total(needs_network):").encode())],
        Config(), Contract(), [], TODAY, root_reader=snapshot.get, report_context=report,
    )
    (finding,) = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert finding.after.text == 'pytest.skip("network tests are disabled")'
    assert report.location(finding.path, finding.after) == ("tests/conftest.py", 11)


# --- reading the chain ----------------------------------------------------------------------


def test_without_a_snapshot_only_the_diffs_conftests_are_read():
    after = module("def test_total(needs_network):")
    assert run(after, reader=False) == ([], "pass")
    conftest = FileChange("tests/conftest.py", "modified", SKIP.encode(), SKIP.replace("{}", "{1: 2}").encode())
    assert run(after, {}, others=[conftest], reader=False) == blocks(("test_total", ADDED))


def test_a_level_that_does_not_parse_ends_the_chain():
    after = module("def test_total(needs_network):")
    assert run(after, {"conftest.py": SKIP, "tests/conftest.py": "def (:\n"}) == ([], "pass")


def test_each_conftest_is_read_once():
    reads = []
    snapshot = {**APP, "tests/conftest.py": SKIP.encode(), "conftest.py": PLAIN.encode()}

    def reader(path):
        reads.append(path)
        return snapshot.get(path)

    after = module("def test_total(needs_network):").encode()
    changes = [FileChange(path, "modified", BEFORE.encode(), after)
               for path in (TEST, "tests/test_other.py")]
    analyze(changes, Config(), Contract(), [], TODAY, root_reader=reader)
    assert sorted(path for path in reads if path.endswith("conftest.py")) == ["conftest.py", "tests/conftest.py"]


def test_an_importer_the_engine_adds_unchanged_reads_no_chain():
    """A root helper's importer joins the analysis unchanged: no module the diff changes (D-093 7)."""
    helper = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
    # No fixture request: a request would also read its conftest for the
    # fixture's own assertions (`_merge_crossfile_oracles`), which is no chain.
    caller = (b"from app.billing import total\nfrom test_helpers import assert_equal\n\n\n"
              b"def test_total():\n    assert_equal(total(), 78.75)\n")
    snapshot = {**APP, "tests/conftest.py": SKIP.encode(), TEST: caller,
                "test_helpers.py": b"def assert_equal(actual, expected):\n    pass\n"}
    reads = []

    def reader(path):
        reads.append(path)
        return snapshot.get(path)

    def searcher(needles):
        return [path for path, data in sorted(snapshot.items()) if any(n.encode() in data for n in needles)]

    _ir, findings, verdict = analyze(
        [FileChange("test_helpers.py", "modified", helper, snapshot["test_helpers.py"])],
        Config(), Contract(), [], TODAY, head_reader=reader, head_searcher=searcher,
        root_reader=reader, root_searcher=searcher,
    )
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.path == TEST for f in findings)
    # The helper is itself a module the diff changes (`test_*.py`), so the
    # root level is read for it; the importer's own level is not.
    assert TEST in reads and [path for path in reads if path.endswith("conftest.py")] == ["conftest.py"]


def test_past_the_read_limit_is_an_engine_error(monkeypatch):
    monkeypatch.setattr(engine, "_MAX_CHAIN_READS", 1)
    with pytest.raises(EngineError, match="conftest chain exceeds the source read limit"):
        run(module("def test_total(needs_network):"))


def test_past_the_byte_limit_is_an_engine_error(monkeypatch):
    monkeypatch.setattr(engine, "_MAX_CHAIN_BYTES", 10)
    with pytest.raises(EngineError, match="conftest chain exceeds the source byte limit"):
        run(module("def test_total(needs_network):"))


def test_a_reader_that_returns_no_bytes_is_an_engine_error():
    with pytest.raises(EngineError, match="conftest chain strict snapshot returned invalid source bytes"):
        analyze([FileChange(TEST, "modified", BEFORE.encode(), BEFORE.encode())],
                Config(), Contract(), [], TODAY, root_reader=lambda path: SKIP if path.endswith("conftest.py") else None)
