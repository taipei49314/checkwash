"""Issue #130: one native test can own several distinct concrete table rows."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

HEADER = 'from app import expand_range\n'
BEFORE = HEADER + '''def test_spans():
    assert expand_range(1, 3) == [1, 2, 3]
    assert expand_range(5, 5) == [5]
'''
AFTER = HEADER + '''def test_spans():
    cases = [(1, 3, [1, 2, 3]), (5, 5, [5])]
    for start, end, expected in cases:
        assert expand_range(start, end) == expected
'''


def run(before=BEFORE, after=AFTER):
    return analyze(
        [FileChange("tests/test_ranges.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _: [],
    )


@pytest.mark.parametrize("before,after", [(BEFORE, AFTER), (AFTER, BEFORE)])
def test_ordered_native_assertions_and_table_preserve_each_oracle(before, after):
    ir, findings, verdict = run(before, after)
    assert verdict == "pass"
    assert not findings
    assert len(ir.files[0].units) == 2


def test_following_new_case_preserves_the_old_complete_prefix():
    _, findings, verdict = run(after=AFTER.replace("(5, 5, [5])]", "(5, 5, [5]), (0, 0, [0])]"))
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [
    AFTER.replace("(5, 5, [5])", "(5, 5, [])"),
    AFTER.replace(", (5, 5, [5])", ""),
    AFTER.replace("[(1, 3, [1, 2, 3]), (5, 5, [5])]", "[(5, 5, [5]), (1, 3, [1, 2, 3])]"),
])
def test_rewritten_removed_or_reordered_original_cases_still_block(after):
    _, findings, verdict = run(after=after)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


def test_multiple_invocations_of_a_single_assert_helper_remain_distinct():
    helper = '''def check(start, end, expected):
    assert expand_range(start, end) == expected
'''
    before = HEADER + helper + '''def test_spans():
    check(1, 3, [1, 2, 3])
    check(5, 5, [5])
'''
    after = HEADER + helper + '''def test_spans():
    for start, end, expected in [(1, 3, [1, 2, 3]), (5, 5, [5])]:
        check(start, end, expected)
'''
    _, findings, verdict = run(before, after)
    assert verdict == "pass"
    assert not findings


def test_impure_statement_between_assertions_does_not_get_projection():
    before = BEFORE.replace("    assert expand_range(5", "    mutate()\n    assert expand_range(5")
    ir, _, _ = run(before)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


NESTED = HEADER + '''def test_spans():
    def check(start, end, expected):
        assert expand_range(start, end) == expected
    check(1, 3, [1, 2, 3])
    check(5, 5, [5])
'''


def test_local_assert_helper_can_be_consolidated_into_a_table():
    _, findings, verdict = run(NESTED)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [
    AFTER.replace("(5, 5, [5])", "(5, 5, [])"),
    AFTER.replace(", (5, 5, [5])", ""),
])
def test_local_helper_oracles_cannot_be_rewritten_or_dropped(after):
    _, findings, verdict = run(NESTED, after)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("before", [
    NESTED.replace("def check(start, end, expected):", "def check(start, end, expected=external()):"),
    NESTED.replace("        assert expand_range", "        mutate()\n        assert expand_range"),
    NESTED.replace("check(1, 3, [1, 2, 3])", "check(*load_case())"),
    NESTED.replace("check(5, 5, [5])", "reference = check"),
])
def test_dynamic_nested_helper_does_not_get_projection(before):
    ir, _, _ = run(before)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
