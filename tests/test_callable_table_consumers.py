"""Literal factory row selection and immutable default-table consumers (#130)."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app import double
def test_one():
    assert double(1) == 2
def test_two():
    assert double(2) == 4
'''
INDEXED = '''from app import double
def test_data():
    return [(1, 2), (2, 4)]
def check(value, expected):
    assert double(value) == expected
def test_one():
    check(*test_data()[0])
def test_two():
    check(*test_data()[1])
'''
DEFAULT = '''from app import double
import pytest
def test_data():
    return [(1, 2), (2, 4)]
def test_default(cases=test_data()):
    for value, expected in cases:
        assert double(value) == expected
@pytest.mark.parametrize("value,expected", test_data())
def test_param(value, expected):
    assert double(value) == expected
'''


def run(after, snapshot=None):
    snapshot = {'app.py': b'def double(value):\n    return value * 2\n', **(snapshot or {})}
    return analyze([FileChange("tests/test_double.py", "modified", BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=snapshot.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("after", [INDEXED, DEFAULT])
def test_accounted_literal_factory_consumers_preserve_all_original_checks(after):
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [INDEXED, DEFAULT])
def test_factory_projection_retains_expectation_changes(after):
    _, findings, verdict = run(after.replace("(2, 4)", "(2, 5)"))
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


def test_factory_projection_retains_missing_original_row():
    _, findings, verdict = run(INDEXED.replace("def test_two():\n    check(*test_data()[1])\n", ""))
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [
    INDEXED.replace("return [(1", "mutate()\n    return [(1"),
    INDEXED.replace("test_data()[0]", "test_data()[index]"),
    INDEXED.replace("test_data()[0]", "test_data()[20]"),
    INDEXED.replace("def test_data():", "@external\ndef test_data():"),
    INDEXED.replace("def test_data():", "def test_data(value=external()):"),
    INDEXED + "saved = test_data\n",
    INDEXED + "test_data.__code__ = external\n",
    INDEXED + "test_data = external\n",
    DEFAULT.replace("(1, 2), (2, 4)", "([1], 2), ([2], 4)"),
    DEFAULT.replace("in cases:", "in cases:\n        cases.clear()"),
    DEFAULT.replace("in cases:", "in cases:\n        assert cases"),
    DEFAULT.replace("cases=test_data()", "cases: external()=test_data()"),
    DEFAULT.replace("cases=test_data()", "cases=test_data(1)"),
    DEFAULT.replace("    for value, expected in cases:", "    mutate()\n    for value, expected in cases:"),
    DEFAULT + "def test_other():\n    test_default(external())\n",
])
def test_unproved_factory_execution_or_shared_default_rows_have_no_projection(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize("after", [INDEXED, DEFAULT])
@pytest.mark.parametrize("path,config", [
    ("pytest.ini", b"[pytest]\nfilterwarnings = error\n"),
    ("pytest.ini", b"[pytest]\naddopts = -W error\n"),
    ("pyproject.toml", b'[tool.pytest.ini_options]\naddopts = "-Werror"\n'),
    ("pytest.ini", b"[pytest]\npython_functions = check_*\n"),
])
def test_collected_return_only_factory_requires_default_pytest_configuration(after, path, config):
    # A return-only test emits PytestReturnNotNoneWarning. Under -W error it
    # fails, so the default-execution proof must not remove that failure.
    ir, _, _ = run(after, {path: config})
    assert not projected(ir)
