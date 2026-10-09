"""Independent regressions for the unverified handover review of #358.

These synthetic examples have no held-out input. A hidden mark must retain
the old guard instead of proving that a real skip cannot run.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from checkwash.frontends.python.own_marks import UNKNOWN
from test_issue358_own_mark_guards import GATE, marks, module, run, setup_markers


@pytest.mark.parametrize("prelude,tests", [
    ("@pytest.fixture(params=[pytest.param(1, marks=pytest.mark.slow)])\n"
     "def sample(request): return request.param\n",
     "def test_total(sample): assert total() == 78.75\n"),
    ("from samples.cases import CASES\n",
     "@pytest.mark.parametrize('sample', CASES)\ndef test_total(sample): assert total() == 78.75\n"),
    ("def values():\n    from samples.cases import CASES\n    return CASES\n",
     "@pytest.mark.parametrize('sample', values())\ndef test_total(sample): assert total() == 78.75\n"),
    ("", "def test_total(): assert total() == 78.75\ntest_total.pytestmark = [pytest.mark.slow]\n"),
    ("", "def test_total(): assert total() == 78.75\ntarget = test_total\ntarget.pytestmark = [pytest.mark.slow]\n"),
    ("", "def test_total(): assert total() == 78.75\npytest.mark.slow(test_total)\n"),
    ("import functools\n@pytest.mark.slow\ndef template(): pass\n",
     "@functools.wraps(template)\ndef test_total(): assert total() == 78.75\n"),
    ("def __getattr__(name):\n    if name == 'pytestmark': return [pytest.mark.slow]\n",
     "def test_total(): assert total() == 78.75\n"),
    ("class Meta(type):\n    def __new__(cls, name, bases, attrs):\n"
     "        attrs['pytestmark'] = [pytest.mark.slow]\n        return super().__new__(cls, name, bases, attrs)\n",
     "class TestBilling(metaclass=Meta):\n    def test_total(self): assert total() == 78.75\n"),
])
def test_hidden_mark_keeps_the_disable(prelude, tests):
    before = module(tests, gate="", prelude=prelude)
    after = module(tests, prelude=prelude)
    found, verdict = run(before, after)
    assert verdict == "block"
    assert any(severity == "high" for _message, severity in found)


@pytest.mark.parametrize("conftest", [
    "import pytest\n@pytest.fixture(autouse=True, params=[pytest.param(1, marks=pytest.mark.slow)])\n"
    "def sample(request): return request.param\n",
    "from tests.marking import pytest_collection_modifyitems\n",
    "def mark(items): pass\npytest_collection_modifyitems = mark\n",
    "import pytest\ndef pytest_runtest_setup(item):\n    item.own_markers.append(pytest.mark.slow.mark)\n",
])
def test_conftest_can_supply_an_unseen_mark(conftest):
    found, verdict = run(module(gate=""), module(), files={"tests/conftest.py": conftest.encode()})
    assert verdict == "block"
    assert any(severity == "high" for _message, severity in found)


@pytest.mark.parametrize("path,config", [
    ("pytest.ini", "[pytest]\naddopts = -p tests.marking\n"),
    ("tests/pytest.ini", "[pytest]\naddopts = -ptests.marking\n"),
    ("pyproject.toml", "[project.entry-points.pytest11]\nmarking = 'tests.marking'\n"),
])
def test_explicit_plugin_configuration_keeps_marks_unknown(path, config):
    found, verdict = run(module(gate=""), module(), files={path: config.encode()})
    assert verdict == "block"
    assert any(severity == "high" for _message, severity in found)


@pytest.mark.parametrize("suffix", [
    "pytest.mark.slow(test_total)",
    "test_total.pytestmark = [pytest.mark.slow]",
    "setattr(test_total, 'pytestmark', [pytest.mark.slow])",
    "test_total.__dict__['pytestmark'] = [pytest.mark.slow]",
])
def test_runtime_mark_actually_skips_in_pytest(tmp_path, suffix):
    """Check the claimed pytest behavior independently of the detector.

    Disable ambient plugin autoload and record the actual xunit skip count;
    never infer runtime behavior from the detector's output.
    """
    source = "import pytest\n" + GATE.replace(" and not os.environ.get('SLOW')", "")
    source += "def test_total(): assert True\n" + suffix + "\n"
    (tmp_path / "test_subject.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_subject.py", "--junitxml=result.xml"],
        cwd=tmp_path, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = ET.parse(tmp_path / "result.xml").findall(".//testcase")
    assert len(cases) == 1 and cases[0].find("skipped") is not None


def test_an_imported_parameter_source_is_unknown_even_outside_tests():
    assert marks("import pytest\nfrom app.cases import CASES\n"
                 "@pytest.mark.parametrize('x', CASES)\ndef test_total(x): pass\n") is UNKNOWN


@pytest.mark.parametrize("binding", [
    "from helpers import pytestmark",
    "def pytestmark(): pass",
    "class pytestmark: pass",
])
def test_overwriting_pytestmark_does_not_keep_the_old_mark(binding):
    assert marks("import pytest\npytestmark = pytest.mark.fast\n" + binding + "\ndef test_total(): pass\n") is UNKNOWN


def test_a_mark_call_with_a_callable_argument_is_not_a_known_decorator():
    assert marks("import pytest\ndef identity(f): return f\n"
                 "@pytest.mark.fast(identity)\ndef test_total(): pass\n") is UNKNOWN


@pytest.mark.parametrize("prelude", [
    "@pytest.mark.parametrize('x', [1, 2])\n",
    "",
])
def test_test_function_name_is_not_assumed_to_be_a_keyword(prelude):
    gate = GATE.replace("request.node.get_closest_marker('slow') and not os.environ.get('SLOW')",
                        "'test_total' not in request.keywords")
    found = setup_markers(module(prelude + "def test_total(x=1): assert total() == 78.75\n", gate=gate))
    assert found["test_total"]


@pytest.mark.parametrize("binding", [
    "from helpers import request",
    "try:\n        pass\n    except Exception as request:\n        pass",
    "match value:\n        case {'key': request}:\n            pass",
])
def test_rebound_fixture_request_is_not_the_test_node(binding):
    gate = GATE.replace("    if request", "    " + binding + "\n    if request")
    assert setup_markers(module(gate=gate))["test_total"]


def test_shadowed_bool_keeps_the_guard_unknown():
    gate = GATE.replace("request.node.get_closest_marker('slow')", "bool(request.node.get_closest_marker('slow'))")
    assert setup_markers(module(gate=gate, prelude="bool = lambda x: x is None\n"))["test_total"]
