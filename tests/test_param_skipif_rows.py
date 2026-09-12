"""Literal true row-level skipif markers cannot be paid for by new rows."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.diffalign import align_file


HEAD = 'import pytest\nfrom billing import total\n'
BODY = 'def test_total(value, expected):\n    assert total(value) == expected\n'


def source(rows, *, extra=''):
    return (HEAD + extra + '@pytest.mark.parametrize("value,expected", ['
            + ', '.join(rows) + '])\n' + BODY)


def side(source):
    return parse_python(source.encode(), collect_tests=True).units[0].side


def unit(before, after):
    return align_file(
        'tests/test_billing.py', 'test', 'modified',
        parse_python(before.encode(), collect_tests=True),
        parse_python(after.encode(), collect_tests=True),
    ).units[0]


@pytest.mark.parametrize('condition', [
    'True', '1', '[1]', '"True"', '"1"', 'condition=True',
    'False, True', 'False, condition=True',
])
def test_proven_true_row_conditions_are_disabled(condition):
    parsed = side(source([f'pytest.param(1, 2, marks=pytest.mark.skipif({condition}, reason="case"))']))
    assert parsed.param_cases == 0
    assert parsed.param_rows[0].disabled == (True,)


@pytest.mark.parametrize('condition', [
    'False', '0', '[]', '"False"', '"0"', 'condition=False',
    'FLAG', 'unknown()', '"sys.platform == \'win32\'"', 'True, condition=False',
])
def test_false_or_unknown_conditions_do_not_become_unconditional_skips(condition):
    parsed = side(source([f'pytest.param(1, 2, marks=pytest.mark.skipif({condition}, reason="case"))']))
    assert parsed.param_cases == 1
    assert parsed.param_rows[0].disabled == (False,)


def test_true_marker_in_mark_sequence_with_pytest_alias():
    after = source([
        'p.param(1, 2, marks=(p.mark.skipif(False), p.mark.skipif(True)))',
    ], extra='import pytest as p\n')
    # Row constructors and their nested markers use trailing components.
    parsed = side(after)
    assert parsed.param_cases == 0
    assert parsed.param_rows[0].disabled == (True,)


def test_skipif_false_to_true_records_only_the_disabling_transition():
    before = source(['pytest.param(1, 2, marks=pytest.mark.skipif(False))', '(2, 4)'])
    after = before.replace('skipif(False)', 'skipif(True)')
    changed = unit(before, after)
    assert changed.delta.param_cases_removed == changed.delta.param_cases_disabled == 1
    assert unit(after, after).delta.param_cases_removed == 0
    assert unit(after, before).delta.param_cases_removed == 0


def test_skipif_and_append_keeps_the_row_identity_floor():
    before = source(['(1, 2)', '(2, 4)'])
    after = source(['pytest.param(1, 2, marks=pytest.mark.skipif(True))', '(2, 4)', '(3, 6)'])
    changed = unit(before, after)
    assert changed.before.param_cases == changed.after.param_cases == 2
    assert changed.delta.param_cases_removed == changed.delta.param_cases_disabled == 1
    _ir, findings, verdict = analyze(
        [FileChange('tests/test_billing.py', 'modified', before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )
    assert verdict == 'block'
    assert [(finding.rule, finding.severity) for finding in findings] == [('TEST_DISABLED', 'high')]


def test_all_rows_can_be_skipped_and_stacked_tables_multiply_loss():
    before = source(['(1, 2)', '(2, 4)'], extra='@pytest.mark.parametrize("rate", [1, 2])\n')
    after = source([
        'pytest.param(1, 2, marks=pytest.mark.skipif(True))',
        'pytest.param(2, 4, marks=pytest.mark.skipif(True))',
    ], extra='@pytest.mark.parametrize("rate", [1, 2])\n')
    before, after = (text.replace('value, expected):', 'value, expected, rate):') for text in (before, after))
    changed = unit(before, after)
    assert changed.before.param_cases == 4
    assert changed.after.param_cases == 0
    assert changed.delta.param_cases_removed == changed.delta.param_cases_disabled == 4
