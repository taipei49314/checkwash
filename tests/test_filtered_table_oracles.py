"""Issue #130: literal predicates partition a finite fixture's concrete rows."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app import common_suffix
def test_overlap():
    assert common_suffix("abc", "xbc") == "bc"
def test_none():
    assert common_suffix("abc", "xyz") == ""
def test_same():
    assert common_suffix("same", "same") == "same"
'''
AFTER = '''import pytest
from app import common_suffix
@pytest.fixture
def rows():
    return [("abc", "xbc", "bc"), ("abc", "xyz", ""), ("same", "same", "same")]
def test_different(rows):
    for a, b, expected in rows:
        if a != b:
            assert common_suffix(a, b) == expected
def test_same(rows):
    for a, b, expected in rows:
        if a == b:
            assert common_suffix(a, b) == expected
'''


def run(after):
    return analyze(
        [FileChange("tests/test_suffix.py", "modified", BEFORE.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _: [],
    )


def test_closed_filtered_consumers_preserve_every_old_row_in_order():
    _, findings, verdict = run(AFTER)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [
    AFTER.replace("if a == b:", "if a != b:"),
    AFTER.replace("(\"same\", \"same\", \"same\")", "(\"same\", \"same\", \"wrong\")"),
])
def test_lost_or_rewritten_filtered_row_still_blocks(after):
    _, findings, verdict = run(after)
    assert verdict == "block"
    assert any(finding.severity == "high" for finding in findings)


@pytest.mark.parametrize("after", [
    AFTER.replace("if a != b:", "if arbitrary(a):"),
    AFTER.replace("if a != b:", "if a is not b:"),
    AFTER.replace("            assert", "            mutate()\n            assert"),
])
def test_unknown_predicate_or_side_effects_get_no_projection(after):
    ir, _, _ = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
