"""Broader concrete-table carriers keep values, object ownership and both contexts."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import double\nimport pytest\n'
BEFORE = (HEADER + 'def test_first():\n    assert double(1) == 2\n'
          'def test_second():\n    assert double(2) == 4\n').encode()
ROWS = '[(1, 2), (2, 4)]'


def after_source(carrier='parametrize', rows=ROWS):
    if carrier == 'parametrize':
        body = ('@pytest.mark.parametrize("value,expected", ' + rows + ')\n'
                'def test_numbers(value, expected):\n    assert double(value) == expected\n')
    elif carrier == 'fixture':
        body = ('@pytest.fixture(params=' + rows + ')\n'
                'def data(request):\n    return request.param\n'
                'def test_numbers(data):\n    value, expected = data\n'
                '    assert double(value) == expected\n')
    elif carrier == 'table-fixture':
        body = ('@pytest.fixture\ndef data():\n    return ' + rows + '\n'
                'def test_numbers(data):\n    for value, expected in data:\n'
                '        assert double(value) == expected\n')
    else:
        body = ('def test_numbers():\n    for value, expected in ' + rows + ':\n'
                '        assert double(value) == expected\n')
    return (HEADER + body).encode()


def run(after=None, *, before=BEFORE, extra=(), snapshot_extra=None):
    after = after if after is not None else after_source()
    changes = [FileChange(PATH, 'modified', before, after), *extra]
    snapshot = {PATH: after, 'app/__init__.py': b'',
                'app/numbers.py': b'def double(value):\n    return value * 2\n',
                **(snapshot_extra or {})}
    for change in extra:
        if change.after is None:
            snapshot.pop(change.path, None)
        else:
            snapshot[change.path] = change.after
    return analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_')
               for file in ir.files if file.path == PATH for unit in file.units)


@pytest.mark.parametrize('extra', [
    FileChange('docs/notes.md', 'modified', b'old explanation\n', b'new explanation\n'),
    FileChange('src/unrelated.py', 'modified', b'FLAG = 1\n', b'FLAG = 2\n'),
    FileChange('src/unrelated.py', 'added', None, b'"""Unrelated metadata."""\nFLAG = 2\n'),
    FileChange('src/unrelated.py', 'deleted', b'FLAG = 1\n', None),
    FileChange('src/unrelated.py', 'modified', b'def other():\n    return 1\n',
               b'# documentation\ndef other():\n    return 1\n'),
])
def test_an_unrelated_inert_second_file_does_not_destroy_the_proof(extra):
    ir, _findings, verdict = run(extra=(extra,))
    assert projected(ir)
    assert verdict == 'pass'


@pytest.mark.parametrize('extra', [
    FileChange('app/numbers.py', 'modified', b'FLAG = 1\n', b'FLAG = 2\n'),
    FileChange('app/__init__.py', 'modified', b'', b'FLAG = 2\n'),
    FileChange('src/unrelated.py', 'modified', b'def other():\n    return 1\n',
               b'def other():\n    return 2\n'),
    FileChange('config.json', 'modified', b'{"enabled": true}', b'{"enabled": false}'),
    FileChange('src/unrelated.py', 'added', None, b'install_patch()\n'),
    FileChange('src/unrelated.py', 'modified', b'FLAG = 1\n', b'FLAG = 2\n', old_path='old.py'),
])
def test_related_executable_or_unknown_cochanges_still_withhold_projection(extra):
    ir, _findings, _verdict = run(extra=(extra,))
    assert not projected(ir)


def test_deleted_ancestor_side_effect_is_checked_on_the_before_snapshot():
    ir, _findings, _verdict = run(extra=(
        FileChange('conftest.py', 'deleted', b'install_patch()\n', None),
    ))
    assert not projected(ir)


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'table-fixture', 'loop'])
def test_module_docstrings_and_literal_named_tables_preserve_each_oracle(carrier):
    preamble = ('"""The full table is kept as module data."""\n'
                'ROWS = ' + ROWS + '\nEXPECTED: int = 2\n').encode()
    before = preamble + BEFORE.replace(b'== 2', b'== EXPECTED')
    after = preamble + after_source(carrier, 'ROWS')
    ir, findings, verdict = run(after, before=before)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('carrier', ['parametrize', 'fixture', 'table-fixture', 'loop'])
def test_named_table_does_not_hide_an_expected_rewrite(carrier):
    after = ('ROWS = [(1, 99), (2, 4)]\n').encode() + after_source(carrier, 'ROWS')
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high'
               for finding in findings)


@pytest.mark.parametrize('preamble', [
    b'__test__ = False\n', b'pytest_plugins = ("evil",)\n',
    b'ROWS = build_rows()\n', b'EXPECTED: install_patch() = 2\n',
    b'EXPECTED = 2\nEXPECTED = 99\n',
])
def test_control_bindings_rebindings_and_executable_annotations_are_not_inert(preamble):
    ir, _findings, _verdict = run(preamble + after_source())
    assert not projected(ir)


def test_function_docstring_does_not_change_a_single_assert_carrier():
    after = after_source().replace(b'def test_numbers(value, expected):\n',
                                  b'def test_numbers(value, expected):\n    """Check every row."""\n')
    ir, findings, verdict = run(after)
    assert projected(ir) and verdict == 'pass' and not findings


def test_module_mutable_object_is_not_substituted_as_a_fresh_literal():
    before = BEFORE.replace(b'double(1)', b'double([1])').replace(b'double(2)', b'double([2])')
    after = (HEADER + 'VALUE = [1]\n'
             '@pytest.mark.parametrize("expected", [2, 4])\n'
             'def test_numbers(expected):\n    assert double(VALUE) == expected\n').encode()
    ir, _findings, _verdict = run(after, before=before)
    assert not projected(ir)


@pytest.mark.parametrize('carrier', ['loop', 'fixture', 'table-fixture'])
def test_repeated_consumers_cannot_copy_mutable_module_rows(carrier):
    before = BEFORE.replace(b'double(1)', b'double([1])').replace(b'double(2)', b'double([2])')
    after = b'ROWS = [([1], 2), ([2], 4)]\n' + after_source(carrier, 'ROWS')
    start = after.index(b'def test_numbers')
    after += after[start:].replace(b'test_numbers', b'test_more')
    ir, _findings, _verdict = run(after, before=before)
    assert not projected(ir)
