"""Issue #130: each function-scoped literal table is freshly allocated."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app import min_max
def test_mixed():
    assert min_max([3, 1, 2]) == (1, 3)
def test_negative():
    assert min_max([-5, 0]) == (-5, 0)
def test_singleton():
    assert min_max([7]) == (7, 7)
'''
AFTER = '''import pytest
from app import min_max
@pytest.fixture
def rows():
    return [([3, 1, 2], (1, 3)), ([-5, 0], (-5, 0)), ([7], (7, 7))]
def check_rows(rows):
    for values, expected in rows:
        assert min_max(values) == expected
def test_mixed(rows):
    check_rows(rows)
def test_negative(rows):
    check_rows(rows)
def test_singleton(rows):
    check_rows(rows)
'''


def run(after):
    return analyze(
        [FileChange("tests/test_minmax.py", "modified", BEFORE.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _: [],
    )


def test_fresh_table_delegated_to_helper_preserves_prefix_for_multiple_consumers():
    _, findings, verdict = run(AFTER)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [
    AFTER.replace("([7], (7, 7))", "([7], (0, 7))"),
    AFTER.replace(", ([7], (7, 7))", ""),
])
def test_fixture_helper_cannot_drop_or_rewrite_original_rows(after):
    _, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [
    AFTER.replace("@pytest.fixture", "@pytest.fixture(scope='module')"),
    AFTER.replace("    for values", "    mutate(rows)\n    for values"),
    AFTER.replace("check_rows(rows)\n", "check_rows(copy_rows(rows))\n"),
    AFTER.replace("    return", "    mutate()\n    return"),
])
def test_unknown_lifetime_or_transform_does_not_get_projection(after):
    ir, _, _ = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
