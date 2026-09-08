"""#130: repeated consumers may share immutable literal params only."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


BEFORE = b'''from app.percent import percent
def test_quarter():
    assert percent(1, 4) == 25
def test_half():
    assert percent(1, 2) == 50
def test_all():
    assert percent(3, 3) == 100
'''
ROWS = b'[(1, 4, 25), (1, 2, 50), (3, 3, 100)]'
AFTER = b'''from app.percent import percent
import pytest
@pytest.fixture(params=''' + ROWS + b''')
def test_data(request):
    return request.param
''' + b''.join(b'''def test_''' + name + b'''(test_data):
    n, total, expected = test_data
    assert percent(n, total) == expected
''' for name in (b'quarter', b'half', b'all'))


def run(after=AFTER, before=BEFORE, extra=None):
    snapshot = {'tests/test_percent.py': after, 'src/app/__init__.py': b'',
                'src/app/percent.py': b'def percent(n, total):\n    return n / total * 100\n',
                **(extra or {})}
    return analyze(
        [FileChange('tests/test_percent.py', 'modified', before, after)],
        Config(), Contract(), [], datetime.date(2026, 1, 1),
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )


def projected(ir):
    return any(u.qualname.startswith('test_concrete_') for u in ir.files[0].units)


def test_012_shared_immutable_rows_keep_old_oracles_and_extra_checks():
    ir, findings, verdict = run()
    assert verdict == 'pass', [(f.rule, f.severity) for f in findings]
    assert not findings
    assert len(ir.files[0].units) == 9
    assert projected(ir)


def test_032_shared_string_rows():
    before = BEFORE.replace(b'percent', b'common_suffix')
    after = AFTER.replace(b'percent', b'common_suffix')
    for old, new in ((b'1, 4', b'"abc", "xbc"'), (b'1, 2', b'"abc", "xyz"'),
                     (b'3, 3', b'"same", "same"'), (b'25', b'"bc"'),
                     (b'50', b'""'), (b'100', b'"same"')):
        before, after = before.replace(old, new), after.replace(old, new)
    ir, findings, verdict = run(after, before)
    assert verdict == 'pass', [(f.rule, f.severity) for f in findings]
    assert not findings and projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace(b'(3, 3, 100)', b'(3, 3, 99)'),
    AFTER.replace(b'(3, 3, 100)', b'(2, 3, 100)'),
    AFTER.replace(b', (3, 3, 100)', b''),
    AFTER.replace(b'def test_quarter', b'@pytest.mark.skip\ndef test_quarter'),
    AFTER.replace(b'    assert percent', b'    if False:\n        assert percent', 1),
    AFTER.replace(b'params=', b'scope="module", params='),
    AFTER.replace(b'params=', b'autouse=True, params='),
    AFTER.replace(b'return request.param', b'return request.param if False else (1, 4, 25)'),
    AFTER.replace(ROWS, b'load_rows()'),
])
def test_real_weakening_or_unproved_execution_keeps_blocking(after):
    _ir, _findings, verdict = run(after)
    assert verdict == 'block'


@pytest.mark.parametrize('literal', [b'[1]', b'{1}', b'{"value": 1}', b'([1],)'])
def test_mutable_param_alias_across_consumers_gets_no_projection(literal):
    before = BEFORE.replace(b'percent(1,', b'percent(' + literal + b',')
    after = AFTER.replace(b'(1,', b'(' + literal + b',')
    ir, _findings, _verdict = run(after, before)
    assert not projected(ir)


@pytest.mark.parametrize('extra', [
    {'conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef reset():\n    yield\n'},
    {'pytest.ini': b'[pytest]\npython_functions = never_*\n'},
    {'pytest.py': b'fixture = lambda *a, **k: lambda f: f\n'},
])
def test_unknown_startup_or_decorator_authority_gets_no_projection(extra):
    ir, _findings, _verdict = run(extra=extra)
    assert not projected(ir)


def test_reordered_old_oracles_get_no_projection():
    ir, _findings, _verdict = run(AFTER.replace(ROWS, b'[(1, 2, 50), (1, 4, 25), (3, 3, 100)]'))
    assert not projected(ir)


def test_uninspected_assertion_in_later_consumer_gets_no_projection():
    ir, _findings, _verdict = run(AFTER + b'    assert False\n')
    assert not projected(ir)


def test_expansion_remains_bounded():
    after = AFTER + b''.join(b'def test_more_' + str(i).encode() + b'''(test_data):
    n, total, expected = test_data
    assert percent(n, total) == expected
''' for i in range(20))
    ir, _findings, _verdict = run(after)
    assert not projected(ir)
