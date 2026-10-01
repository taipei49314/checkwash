"""A skip or xfail reached while pytest sets a test up disables it (#172).

Family: an outcome the unit reaches during setup, outside its own body and
markers - a requested or autouse fixture, what that fixture requests, or the
xunit setup pytest calls. Conftest fixtures are suite-level runtime controls;
a test module's own providers mark the units that reach them. Every path
reads the one definition in `setup_skip_controls.callback_outcome`.
"""
import datetime
import os
import subprocess
import sys

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python

CONFTEST = (
    "import pytest\n\n\n"
    "@pytest.fixture\n"
    "def items():\n"
    "    return [{'price': 10.0, 'qty': 3}, {'price': 5.0, 'qty': 9}]\n"
)
HEAD = "def items():\n"
MODULE = (
    "import pytest\n\n\n"
    "@pytest.fixture\n"
    "def db():\n"
    "    pytest.skip('migrating')\n"
    "    yield\n\n\n"
)
SETUP = "    pytest.skip('migrating')\n    yield\n"
AUTOUSE = "@pytest.fixture(autouse=True)\ndef _isolated():\n    pytest.skip('isolated')\n    yield\n"


def disabled(after, before, path="tests/conftest.py"):
    change = FileChange(path, "added" if before is None else "modified",
                        None if before is None else before.encode(), after.encode())
    findings = analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 1))[1]
    return [f for f in findings if f.rule == "TEST_DISABLED"]


def conftest(statements, imports=""):
    source = CONFTEST.replace("import pytest\n", "import pytest\n" + imports, 1)
    return source.replace(HEAD, HEAD + statements, 1)


def setup_names(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    return {
        unit.qualname: sorted(m.name for m in unit.side.markers if m.name.startswith("setup."))
        for unit in parsed.units
    }


@pytest.mark.parametrize("after", [
    conftest("    pytest.skip('temporarily unavailable')\n"),
    conftest("    pytest.xfail('known bad')\n"),
    conftest("    pytest.skip(reason='temporarily unavailable')\n"),
    conftest("    pytest.skip(f'{__name__} temporarily unavailable')\n"),
    conftest("    raise pytest.skip.Exception('temporarily unavailable')\n"),
    conftest("    raise pytest.skip.Exception('temporarily unavailable') from None\n"),
    conftest("    raise unittest.SkipTest('temporarily unavailable')\n", "import unittest\n"),
    conftest("    raise SkipTest('temporarily unavailable')\n", "from unittest import SkipTest\n"),
    conftest("    skip('temporarily unavailable')\n", "from pytest import skip\n"),
    conftest("    total = 0\n    pytest.skip('temporarily unavailable')\n"),
    conftest("    if True:\n        pytest.skip('temporarily unavailable')\n"),
    conftest("    try:\n        pytest.skip('temporarily unavailable')\n    finally:\n        pass\n"),
    CONFTEST.replace("import pytest\n", "import pytest as pt\n").replace("@pytest.fixture", "@pt.fixture")
    .replace(HEAD, HEAD + "    pt.skip('temporarily unavailable')\n"),
    CONFTEST + "\n\n" + AUTOUSE,
])
def test_unconditional_conftest_fixture_skip_is_a_suite_control(after):
    found = disabled(after, CONFTEST)
    assert len(found) == 1, found
    assert found[0].severity == "high" and found[0].unit == "<suite>"
    assert "conftest fixture setup" in found[0].message


def test_new_conftest_with_a_skipping_autouse_fixture_is_a_suite_control():
    after = "import pytest\n\n\n" + AUTOUSE
    assert [f.severity for f in disabled(after, None)] == ["high"]


@pytest.mark.parametrize("after", [
    conftest("    if not os.environ.get('BILLING_FIXTURES'):\n        pytest.skip('needs fixtures')\n", "import os\n"),
    conftest("    if False:\n        pytest.skip('temporarily unavailable')\n"),
    conftest("    for path in glob.glob('samples/*.json'):\n        return path\n    pytest.skip('no sample')\n",
             "import glob\n"),
    conftest("    return pytest.importorskip('numpy')\n"),
    conftest("    custom.skip('temporarily unavailable')\n", "import custom\n"),
    # An unbound cause raises NameError first: the test errors, it is not skipped.
    conftest("    raise pytest.skip.Exception('temporarily unavailable') from error\n"),
    conftest("    def later():\n        pytest.skip('never called')\n"),
    CONFTEST.replace("    return", "    yield") + "    pytest.skip('teardown only')\n",
    CONFTEST + "\n\ndef helper():\n    pytest.skip('not a fixture')\n",
    conftest("    pytest.skip('replaced')\n") + "\n\n@pytest.fixture\ndef items():\n    return []\n",
])
def test_guarded_teardown_and_unexecuted_skips_stay_silent(after):
    assert not disabled(after, CONFTEST)


def test_rewording_an_existing_fixture_skip_is_not_a_new_event():
    before = conftest("    pytest.skip('temporarily unavailable')\n")
    after = conftest("    pytest.skip(reason='blocked on the billing migration')\n")
    assert not disabled(after, before)


def test_dropping_the_guard_of_a_fixture_skip_makes_it_unconditional():
    before = conftest("    if not os.environ.get('CI'):\n        pytest.skip('local only')\n", "import os\n")
    after = conftest("    pytest.skip('local only')\n", "import os\n")
    assert [f.severity for f in disabled(after, before)] == ["high"]


def test_same_file_fixture_reaches_the_units_that_request_it():
    source = MODULE + (
        "def test_param(db):\n    assert db is None\n\n\n"
        "@pytest.mark.usefixtures('db')\n"
        "def test_used():\n    assert True\n\n\n"
        "@pytest.fixture\n"
        "def rows(db):\n    return [1]\n\n\n"
        "def test_chain(rows):\n    assert rows == [1]\n\n\n"
        "def test_free():\n    assert True\n"
    )
    assert setup_names(source) == {
        "test_param": ["setup.db.skip"],
        "test_used": ["setup.db.skip"],
        "test_chain": ["setup.db.skip"],
        "test_free": [],
    }


def test_direct_parametrize_runs_no_fixture_and_indirect_does():
    source = MODULE + (
        "@pytest.mark.parametrize('db', [1, 2])\n"
        "def test_direct(db):\n    assert db\n\n\n"
        "@pytest.mark.parametrize('db', [1, 2], indirect=True)\n"
        "def test_indirect(db):\n    assert db\n"
    )
    assert setup_names(source) == {"test_direct": [], "test_indirect": ["setup.db.skip"]}


def test_autouse_class_fixtures_and_xunit_setup_reach_their_units():
    source = (
        "import unittest\n\n"
        "import pytest\n\n\n"
        "def setup_function(function):\n    pytest.skip('functions only')\n\n\n"
        "def test_function():\n    assert True\n\n\n"
        "class TestPlain:\n"
        "    def setup_method(self, method):\n        pytest.xfail('known')\n\n"
        "    def test_method(self):\n        assert True\n\n\n"
        "class TestUnit(unittest.TestCase):\n"
        "    def setUp(self):\n        self.skipTest('later')\n\n"
        "    def test_case(self):\n        self.assertEqual(1, 1)\n\n\n"
        "class TestAutouse:\n"
        "    @pytest.fixture(autouse=True)\n"
        "    def _env(self):\n        raise pytest.skip.Exception('isolated')\n\n"
        "    def test_auto(self):\n        assert True\n"
    )
    assert setup_names(source) == {
        "test_function": ["setup.setup_function.skip"],
        "TestPlain.test_method": ["setup.setup_method.xfail"],
        "TestUnit.test_case": ["setup.setUp.skip"],
        "TestAutouse.test_auto": ["setup._env.skip"],
    }


@pytest.mark.parametrize("setup", [
    "    if not os.environ.get('DB'):\n        pytest.skip('no db')\n    yield\n",
    "    yield\n    pytest.skip('teardown')\n",
    "    pytest.importorskip('sqlite3')\n    yield\n",
])
def test_guarded_teardown_or_environment_skips_mark_nothing(setup):
    source = MODULE.replace(SETUP, setup) + "def test_param(db):\n    assert db is None\n"
    assert setup_names(source) == {"test_param": []}


def test_test_module_fixture_skip_blocks_the_requesting_test():
    before = (
        "import pytest\n\nfrom app.billing import invoice_total\n\n\n"
        "@pytest.fixture\n"
        "def items():\n"
        "    return [{'price': 10.0, 'qty': 3}]\n\n\n"
        "def test_invoice_total(items):\n"
        "    assert invoice_total(items) == 31.5\n"
    )
    after = before.replace("def items():\n", "def items():\n    pytest.skip('temporarily unavailable')\n")
    found = disabled(after, before, path="tests/test_billing.py")
    assert [(f.unit, f.severity) for f in found] == [("test_invoice_total", "high")]


def test_xunit_setup_skip_added_to_an_existing_class_blocks():
    before = (
        "from app.billing import total\n\n\n"
        "class TestBilling:\n"
        "    def test_total(self):\n"
        "        assert total() == 3\n"
    )
    after = before.replace(
        "class TestBilling:\n",
        "class TestBilling:\n    def setup_method(self):\n        pytest.skip('later')\n\n",
    ).replace("from app.billing import total\n", "import pytest\n\nfrom app.billing import total\n")
    found = disabled(after, before, path="tests/test_billing.py")
    assert [(f.unit, f.severity) for f in found] == [("TestBilling.test_total", "high")]


@pytest.mark.parametrize("statement, outcome", [
    ("    pytest.skip('temporarily unavailable')\n", "1 skipped"),
    ("    pytest.xfail('known bad')\n", "1 xfailed"),
])
def test_real_conftest_fixture_skip_turns_a_failure_green(tmp_path, statement, outcome):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_billing.py").write_text(
        "def test_total(items):\n    assert sum(i['price'] * i['qty'] for i in items) == 1\n",
        encoding="utf-8",
    )
    (tests / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    before = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 1 and "1 failed" in before.stdout, before.stdout + before.stderr
    after = conftest(statement)
    (tests / "conftest.py").write_text(after, encoding="utf-8")
    run = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0 and outcome in run.stdout, run.stdout + run.stderr
    assert [f.severity for f in disabled(after, CONFTEST)] == ["high"]


TEST_METHOD = "    def test_method(self):\n        assert True\n"


@pytest.mark.parametrize("definition, expected", [
    # Only unittest runs setUp/setUpClass: on a plain class pytest calls neither.
    ("class TestPlain:\n    def setUp(self):\n        pytest.skip('later')\n\n", []),
    ("class TestPlain(object):\n    @classmethod\n"
     "    def setUpClass(cls):\n        pytest.skip('later')\n\n", []),
    ("class TestPlain(unittest.TestCase):\n    @classmethod\n"
     "    def setUpClass(cls):\n        pytest.skip('later')\n\n", ["setup.setUpClass.skip"]),
    # A base the module does not define may be a TestCase.
    ("class TestPlain(StoreCase):\n    def setUp(self):\n        pytest.skip('later')\n\n",
     ["setup.setUp.skip"]),
    ("class TestPlain:\n    def setup_method(self, method):\n        pytest.skip('later')\n\n",
     ["setup.setup_method.skip"]),
])
def test_unittest_setup_reaches_only_a_class_that_can_be_a_testcase(definition, expected):
    header = "import unittest\n\nimport pytest\n\nfrom app.testing import StoreCase\n\n\n"
    assert setup_names(header + definition + TEST_METHOD) == {"TestPlain.test_method": expected}


@pytest.mark.parametrize("module_setup, expected", [
    ("def setup_module(module):\n    pytest.skip('later')\n", ["setup.setup_module.skip"]),
    # pytest calls only the first of setUpModule and setup_module it finds.
    ("def setUpModule():\n    pass\n\n\ndef setup_module(module):\n    pytest.skip('later')\n", []),
    ("def setUpModule():\n    pytest.skip('later')\n\n\ndef setup_module(module):\n    pass\n",
     ["setup.setUpModule.skip"]),
])
def test_module_setup_is_the_first_one_pytest_finds(module_setup, expected):
    source = "import pytest\n\n\n" + module_setup + "\n\ndef test_function():\n    assert True\n"
    assert setup_names(source) == {"test_function": expected}


@pytest.mark.parametrize("tests, expected", [
    # A class or module `parametrize` supplies the argname, so its fixture never runs.
    ("@pytest.mark.parametrize('db', [1, 2])\n"
     "class TestStore:\n    def test_row(self, db):\n        assert db\n", {"TestStore.test_row": []}),
    ("pytestmark = pytest.mark.parametrize('db', [1, 2])\n\n\n"
     "def test_row(db):\n    assert db\n", {"test_row": []}),
    # The direct value also replaces the fixture for the fixtures the unit requests.
    ("@pytest.fixture\ndef rows(db):\n    return [db]\n\n\n"
     "@pytest.mark.parametrize('db', [1, 2])\ndef test_row(rows):\n    assert rows\n", {"test_row": []}),
    # Indirect parametrization still runs the fixture.
    ("@pytest.mark.parametrize('db', [1, 2], indirect=True)\n"
     "class TestStore:\n    def test_row(self, db):\n        assert db\n",
     {"TestStore.test_row": ["setup.db.skip"]}),
])
def test_class_and_module_parametrize_run_no_fixture(tests, expected):
    assert setup_names(MODULE + tests) == expected
