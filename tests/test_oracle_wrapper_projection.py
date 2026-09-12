"""Complete local wrapper bodies must preserve every concrete assertion."""

import datetime
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import double\n'
BEFORE = (HEADER + 'def test_first():\n    assert double(1) == 2\n'
          'def test_second():\n    assert double(2) == 4\n').encode()
DECORATOR = '''import functools
def expect(expected):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper():
            assert fn() == expected
        return wrapper
    return deco
@expect(2)
def test_first():
    return double(1)
@expect(4)
def test_second():
    return double(2)
'''
CONTEXT = '''from contextlib import contextmanager
@contextmanager
def expect(expected):
    box = {}
    yield box
    assert box["got"] == expected
def test_first():
    with expect(2) as box:
        box["got"] = double(1)
def test_second():
    with expect(4) as box:
        box["got"] = double(2)
'''


def run(after, before=BEFORE, context=None):
    snapshot = {PATH: after, 'app/__init__.py': b'',
                'app/numbers.py': b'def double(value):\n    return value * 2\n', **(context or {})}
    return analyze([FileChange(PATH, 'modified', before, after)], Config(), Contract(), [],
                   datetime.date(2026, 9, 12), root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('body', [DECORATOR, CONTEXT])
def test_complete_decorator_and_contextmanager_preserve_checks_in_both_directions(body):
    wrapped = (HEADER + body).encode()
    for before, after in [(BEFORE, wrapped), (wrapped, BEFORE)]:
        ir, findings, verdict = run(after, before)
        assert projected(ir) and verdict == 'pass'
        assert not findings


@pytest.mark.parametrize('body', [DECORATOR, CONTEXT])
def test_wrapper_expected_rewrites_remain_high(body):
    ir, findings, verdict = run((HEADER + body.replace('expect(2)', 'expect(99)')).encode())
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high' for finding in findings)


@pytest.mark.parametrize('body', [
    DECORATOR.replace('assert fn() == expected', 'fn()'),
    DECORATOR.replace('assert fn() == expected', 'assert True'),
    DECORATOR.replace('assert fn() == expected', 'assert fn() == expected\n            install_patch()'),
    DECORATOR.replace('return wrapper', 'return fn'),
    DECORATOR.replace('@functools.wraps(fn)', '@hide(fn)'),
    DECORATOR.replace('return double(1)', 'return double(1)\n    install_patch()'),
    DECORATOR.replace('@expect(2)', '@expect(2)\n@skip'),
    DECORATOR.replace('def expect(expected):', 'def expect(functools):').replace('== expected', '== functools'),
    CONTEXT.replace('    assert box["got"] == expected', '    assert True'),
    CONTEXT.replace('    yield box', '    if expected:\n        yield box'),
    CONTEXT.replace('    yield box', '    try:\n        yield box\n    except Exception:\n        pass'),
    CONTEXT.replace('box["got"] = double(1)', 'box["got"] = double(box)'),
    CONTEXT.replace('box["got"] = double(1)', 'box["got"] = double(1)\n        box.clear()'),
    CONTEXT + '\nexpect = replacement\n',
])
def test_wrapper_side_effects_exception_suppression_and_unproved_dispatch_receive_no_credit(body):
    ir, _findings, _verdict = run((HEADER + body).encode())
    assert not projected(ir)


@pytest.mark.parametrize('body,module', [(DECORATOR, 'functools'), (CONTEXT, 'contextlib')])
@pytest.mark.parametrize('prefix', ['', 'src/', 'tests/'])
def test_repository_wrapper_replacements_are_not_standard_library_authority(body, module, prefix):
    ir, _findings, _verdict = run((HEADER + body).encode(), context={prefix + module + '.py': b''})
    assert not projected(ir)


@pytest.mark.parametrize('case_name', ['CASE_009_parse_ints', 'CASE_017_cap_words', 'EXT_030_unquote'])
def test_retained_wrapper_refactor_sources_preserve_every_original_check(case_name):
    case = Path(__file__).parents[1] / 'benchmarks' / 'refactors' / 'cases' / case_name
    before_root, after_root = case / 'BEFORE', case / 'AFTER'
    before = {path.relative_to(before_root).as_posix(): path.read_bytes() for path in before_root.rglob('*') if path.is_file()}
    after = {path.relative_to(after_root).as_posix(): path.read_bytes() for path in after_root.rglob('*') if path.is_file()}
    changes = [FileChange(path, 'modified', before[path], after[path]) for path in before.keys() & after.keys()
               if before[path] != after[path]]
    ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                                    root_reader=after.get,
                                    root_searcher=lambda needles: search_source_mapping(after, needles))
    assert projected(ir) and verdict == 'pass'
    assert not findings
