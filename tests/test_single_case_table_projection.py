"""The concrete table proof has no semantic minimum of two baseline tests."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze


BEFORE = b'''from app import double
def test_first():
    assert double(1) == 2
'''


def table_source(carrier, rows):
    header = 'from app import double\nimport pytest\n'
    if carrier == 'parametrize':
        return (header + '@pytest.mark.parametrize("value,expected", ' + rows + ')\n'
                'def test_double(value, expected):\n    assert double(value) == expected\n').encode()
    if carrier == 'fixture':
        return (header + '@pytest.fixture(params=' + rows + ')\n'
                'def data(request):\n    return request.param\n'
                'def test_double(data):\n    value, expected = data\n'
                '    assert double(value) == expected\n').encode()
    return (header + 'def test_double():\n    for value, expected in ' + rows + ':\n'
            '        assert double(value) == expected\n').encode()


def run(after, *, snapshot=None, before=BEFORE):
    snapshot = snapshot or {}
    return analyze(
        [FileChange('tests/test_double.py', 'modified', before, after)],
        Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader=snapshot.get, root_searcher=lambda _needles: sorted(snapshot),
    )


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'loop'])
@pytest.mark.parametrize('rows,count', [('[(1, 2)]', 1), ('[(1, 2), (2, 4)]', 2)])
def test_one_baseline_case_keeps_its_oracle_and_optional_following_rows(carrier, rows, count):
    ir, findings, verdict = run(table_source(carrier, rows))
    assert projected(ir)
    assert len(ir.files[0].units) == count
    assert verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'loop'])
def test_single_case_projection_keeps_changed_expected_visible(carrier):
    ir, findings, verdict = run(table_source(carrier, '[(1, 99), (2, 4)]'))
    assert projected(ir)
    assert verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high'
               for finding in findings)


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'loop'])
@pytest.mark.parametrize('rows', ['[]', '[(2, 4)]', '[(2, 4), (1, 2)]'])
def test_single_case_proof_does_not_cover_removed_or_reordered_inputs(carrier, rows):
    ir, _findings, _verdict = run(table_source(carrier, rows))
    assert not projected(ir)


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'loop'])
def test_one_baseline_case_still_requires_inert_startup(carrier):
    ir, _findings, _verdict = run(
        table_source(carrier, '[(1, 2)]'), snapshot={'conftest.py': b'reset_subject()\n'},
    )
    assert not projected(ir)
