"""Issue #130: direct literal-return factories in pytest parametrization."""
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
AFTER = '''import pytest
from app import double
def rows():
    return [(1, 2), (2, 4)]
@pytest.mark.parametrize("value,expected", rows())
def test_double(value, expected):
    assert double(value) == expected
'''


def run(after):
    return analyze(
        [FileChange("tests/test_double.py", "modified", BEFORE.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={'app.py': b'def double(value):\n    return value * 2\n'}.get, root_searcher=lambda _: [],
    )


@pytest.mark.parametrize("after", [AFTER, AFTER.replace("[(1, 2), (2, 4)]", "{1: 2, 2: 4}").replace("rows())", "rows().items())")])
def test_closed_table_factory_preserves_oracles(after):
    _, findings, verdict = run(after)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [
    AFTER.replace("(2, 4)", "(2, 5)"),
    AFTER.replace(", (2, 4)", ""),
])
def test_table_factory_does_not_hide_changed_or_missing_oracles(after):
    _, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [
    AFTER.replace("    return", "    mutate()\n    return"),
    AFTER.replace("def rows():", "def rows(value=external()):"),
    AFTER.replace("def rows():", "@external\ndef rows():"),
    AFTER.replace("@pytest.mark.parametrize", "rows = external\n@pytest.mark.parametrize"),
    AFTER.replace("@pytest.mark.parametrize", "rows.__code__ = external\n@pytest.mark.parametrize"),
    AFTER.replace("@pytest.mark.parametrize", "saved = rows\n@pytest.mark.parametrize"),
    AFTER.replace("[(1, 2), (2, 4)]", "load_rows()"),
    AFTER.replace("rows())", "rows(1))"),
])
def test_dynamic_or_reused_factory_has_no_equivalence_proof(after):
    ir, _, _ = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
