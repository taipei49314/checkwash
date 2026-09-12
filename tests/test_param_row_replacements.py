"""Re-keying a row and replacing its oracle cannot hide behind equal counts."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.expectation_definition import _column_expectation_edited
from checkwash.engine import FileChange, analyze
from checkwash.ir.model import ParamTable, UnitSide


def table(*rows, disabled=None):
    return UnitSide(span=(0, 0), param_rows=(ParamTable(
        ('value', 'expected'), tuple(rows), disabled or tuple(False for _ in rows),
    ),))


def edited(before, after):
    return _column_expectation_edited('expected', before, after)


@pytest.mark.parametrize('after', [
    table(('2', '4'), ('3', '6')),
    table(('2', '4'), ('3', '6'), ('4', '8')),
])
def test_vanished_input_and_new_answer_have_a_replacement_owner(after):
    assert edited(table(('1', '2'), ('2', '4')), after)


def test_partial_removal_of_a_duplicate_input_keeps_oracle_multiplicity():
    before = table(('1', '2'), ('1', '3'), ('2', '4'))
    assert edited(before, table(('1', '2'), ('2', '4'), ('3', '6')))
    before = table(('1', '2'), ('1', '2'), ('2', '4'))
    assert edited(before, table(('2', '4'), ('3', '2'), ('4', '8')))


@pytest.mark.parametrize('after', [
    table(('3', '2'), ('2', '4')),
    table(('3', '2'), ('2', '4'), ('4', '8')),
    table(('2', '4'), ('1', '2')),
    table(('1', '2'), ('2', '4'), ('3', '6')),
    table(('2', '4')),
])
def test_input_edits_reorders_pure_additions_and_net_deletions_keep_their_owner(after):
    assert not edited(table(('1', '2'), ('2', '4')), after)


def test_skip_and_append_is_only_a_disabling_event():
    before = table(('1', '2'), ('2', '4'))
    after = table(('1', '2'), ('2', '4'), ('3', '6'), disabled=(True, False, False))
    assert not edited(before, after)


def test_removing_an_already_disabled_row_is_not_a_lost_live_oracle():
    before = table(('1', '2'), ('2', '4'), disabled=(True, False))
    assert not edited(before, table(('2', '4'), ('3', '6')))


def test_same_input_changed_answer_remains_owned_by_135():
    before = table(('1', '2'), ('2', '4'))
    assert edited(before, table(('1', '99'), ('2', '4'), ('3', '6')))
    assert edited(before, table(('1', '4'), ('2', '2'), ('3', '6')))


def source(rows):
    return ('import pytest\nfrom billing import total\n'
            '@pytest.mark.parametrize("value,expected", [' + ', '.join(rows) + '])\n'
            'def test_total(value, expected):\n    assert total(value) == expected\n').encode()


@pytest.mark.parametrize('rows,rule', [
    (['(2, 4)', '(3, 6)'], 'EXPECTATION_DEFINITION_CHANGED'),
    (['pytest.param(2, 4)', 'pytest.param(3, 6)'], 'EXPECTATION_DEFINITION_CHANGED'),
    (['pytest.param(1, 2, marks=pytest.mark.skip)', '(2, 4)', '(3, 6)'], 'TEST_DISABLED'),
])
def test_shipping_pipeline_reports_replacement_without_duplicating_skip(rows, rule):
    _ir, findings, verdict = analyze(
        [FileChange('tests/test_billing.py', 'modified', source(['(1, 2)', '(2, 4)']), source(rows))],
        Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )
    assert verdict == 'block'
    assert [(finding.rule, finding.severity) for finding in findings] == [(rule, 'high')]
