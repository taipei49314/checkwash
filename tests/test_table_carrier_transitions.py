"""Concrete oracles survive reverse table conversions and transparent loop helpers."""

import datetime
import itertools

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import double\nimport pytest\n'
ROWS = '[(1, 2), (2, 4), (3, 6)]'
CARRIERS = ['native', 'parametrize', 'fixture', 'loop', 'helper']


def source(carrier, rows=ROWS):
    if carrier == 'native':
        body = ''.join(f'def test_{value}():\n    assert double({value}) == {value * 2}\n'
                       for value in (1, 2, 3))
    elif carrier == 'parametrize':
        body = ('@pytest.mark.parametrize("value,expected", ' + rows + ')\n'
                'def test_numbers(value, expected):\n    assert double(value) == expected\n')
    elif carrier == 'fixture':
        body = ('@pytest.fixture(params=' + rows + ')\n'
                'def data(request):\n    return request.param\n'
                'def test_numbers(data):\n    value, expected = data\n'
                '    assert double(value) == expected\n')
    elif carrier == 'helper':
        body = ('def assert_rows(rows):\n    for value, expected in rows:\n'
                '        assert double(value) == expected\n'
                'def test_numbers():\n    assert_rows(' + rows + ')\n')
    else:
        body = ('ROWS = ' + rows + '\n'
                'def test_numbers():\n    for value, expected in ROWS:\n'
                '        assert double(value) == expected\n')
    return (HEADER + body).encode()


def run(before, after, *, context=None):
    snapshot = {PATH: after, 'app/__init__.py': b'',
                'app/numbers.py': b'def double(value):\n    return value * 2\n',
                **(context or {})}
    return analyze(
        [FileChange(PATH, 'modified', before, after)], Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('before,after', [pair for pair in itertools.product(CARRIERS, repeat=2) if pair[0] != pair[1]])
def test_closed_carriers_preserve_the_complete_concrete_sequence_in_both_directions(before, after):
    ir, findings, verdict = run(source(before), source(after))
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('carrier', ['fixture', 'loop', 'helper'])
def test_previously_unreadable_table_carrier_keeps_expected_rewrites_visible(carrier):
    ir, findings, verdict = run(source(carrier), source(carrier, '[(1, 99), (2, 4), (3, 6)]'))
    assert projected(ir)
    assert verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high'
               for finding in findings)


def test_inline_parametrize_retains_135_ownership_instead_of_relabelling_it():
    ir, findings, verdict = run(source('parametrize'), source('parametrize', '[(1, 99), (2, 4), (3, 6)]'))
    assert not projected(ir)
    assert verdict == 'block'
    assert [(finding.rule, finding.severity) for finding in findings] == [('EXPECTATION_DEFINITION_CHANGED', 'high')]


def test_module_named_parametrize_table_exposes_values_the_ordinary_rows_cannot_read():
    before = b'ROWS = ' + ROWS.encode() + b'\n' + source('parametrize', 'ROWS')
    after = before.replace(b'(1, 2)', b'(1, 99)', 1)
    ir, findings, verdict = run(before, after)
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' for finding in findings)


@pytest.mark.parametrize('carrier', ['fixture', 'loop', 'helper'])
def test_a_carrier_conversion_still_requires_unchanged_ordered_input_coverage(carrier):
    ir, _findings, _verdict = run(source('parametrize'), source(carrier, '[(3, 6), (1, 2), (2, 4)]'))
    assert not projected(ir)


@pytest.mark.parametrize('replacement', [
    b'        pass\n',
    b'        if value:\n            assert double(value) == expected\n',
    b'        assert double(value) == expected\n        rows.clear()\n',
    b'        assert double(value) == expected, "message"\n',
    b'        assert double(value) == len(rows)\n',
])
def test_loop_helpers_must_check_every_row_without_additional_execution(replacement):
    after = source('helper').replace(b'        assert double(value) == expected\n', replacement)
    ir, _findings, _verdict = run(source('native'), after)
    assert not projected(ir)


def test_runtime_startup_still_precludes_reverse_or_helper_projection():
    ir, _findings, _verdict = run(source('parametrize'), source('helper'),
                                context={'conftest.py': b'install_patch()\n'})
    assert not projected(ir)


def test_loop_helper_keeps_its_real_assertion_evidence_and_row_value():
    ir, _findings, _verdict = run(source('native'), source('helper'))
    assertion = ir.files[0].units[1].after.assertions[0]
    assert assertion.left == 'double(2)'
    assert assertion.right_value == '4'
    assert assertion.span[0] < source('helper').index(b'def test_numbers')
