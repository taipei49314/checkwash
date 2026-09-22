"""A try/except sentinel is an exception oracle, not a standalone tautology."""
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.classic_raises import mark_classic_exception_removal
from checkwash.frontends.python.frontend import parse_python
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_divide.py'
PROD = b'def safe_divide(a, b):\n    return None if b == 0 else a / b\n'
BEFORE = '''from app.prod import safe_divide
def test_div_zero():
    try:
        safe_divide(1, 0)
        assert False
    except ZeroDivisionError:
        pass
'''
AFTER = '''from app.prod import safe_divide
def test_div_zero():
    result = safe_divide(1, 0)
    assert result is None
'''


def project(before=BEFORE, after=AFTER, *, extra=None, production=PROD):
    old, new = before.encode(), after.encode()
    head = {'src/app/__init__.py': b'', 'src/app/prod.py': production, PATH: new, **(extra or {})}
    old_parsed, new_parsed = parse_python(old, True), parse_python(new, True)
    result, _ = mark_classic_exception_removal(old, new, old_parsed, new_parsed, path=PATH,
        root_reader=head.get, root_searcher=lambda needles: search_source_mapping(head, needles),
        changes=[FileChange(path=PATH, before=old, after=new, status='modified')])
    return result, old_parsed


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('    result = safe_divide(1, 0)\n    assert result',
                                                       '    assert safe_divide(1, 0)')])
def test_removed_closed_exception_oracle_blocks(after):
    old, new = BEFORE.encode(), after.encode()
    head = {'src/app/__init__.py': b'', 'src/app/prod.py': PROD, PATH: new}
    result = analyze([FileChange(path=PATH, before=old, after=new, status='modified')],
        Config(), Contract(), [], datetime.date(2026, 9, 21), known_modules={'app'}, self_modules={'app'},
        head_reader=head.get, head_searcher=lambda needles: search_source_mapping(head, needles),
        root_reader=head.get, root_searcher=lambda needles: search_source_mapping(head, needles))
    assert result[2] == 'block'
    assert any(f.rule == 'ASSERT_REMOVED' for f in result[1])
    before_ir, _ = project(after=after)
    oracle = before_ir.units[0].side.assertions[0]
    assert oracle.form == 'raises' and oracle.strength is None and not oracle.trivial
    assert 'try:' in oracle.text and 'except ZeroDivisionError:' in oracle.text


@pytest.mark.parametrize('before,after', [
    (BEFORE, BEFORE),
    (BEFORE, AFTER.replace('is None', '== 0')),
    (BEFORE.replace('assert False', 'assert True'), AFTER),
    (BEFORE.replace('assert False', 'assert False, callback()'), AFTER),
    (BEFORE.replace('except ZeroDivisionError:', 'except AssertionError:'), AFTER),
    (BEFORE.replace('except ZeroDivisionError:', 'except ZeroDivisionError as error:'), AFTER),
    (BEFORE.replace('        pass', '        callback()'), AFTER),
    (BEFORE.replace('        pass', '        pass\n    finally:\n        callback()'), AFTER),
    (BEFORE.replace('test_div_zero():', 'test_div_zero(request):'), AFTER),
    (BEFORE.replace('safe_divide(1, 0)', 'safe_divide(callback(), 0)'),
     AFTER.replace('safe_divide(1, 0)', 'safe_divide(callback(), 0)')),
    (BEFORE.replace('safe_divide(1, 0)', 'safe_divide(*values)'),
     AFTER.replace('safe_divide(1, 0)', 'safe_divide(*values)')),
    (BEFORE.replace('safe_divide(1, 0)', 'safe_divide(**values)'),
     AFTER.replace('safe_divide(1, 0)', 'safe_divide(**values)')),
    (BEFORE, AFTER.replace('safe_divide(1, 0)', 'safe_divide(2, 0)')),
    (BEFORE + 'def test_other():\n    callback()\n', AFTER + 'def test_other():\n    callback()\n'),
    (BEFORE, AFTER.replace('result =', 'safe_divide =').replace('assert result', 'assert safe_divide')),
])
def test_unknown_or_changed_context_retains_original_ir(before, after):
    projected, original = project(before, after)
    assert projected is original


@pytest.mark.parametrize('extra', [
    {'conftest.py': b'def pytest_configure():\n    callback()\n'},
    {'src/app/__init__.py': b'callback()\n'},
])
def test_startup_hooks_withhold_projection(extra):
    projected, original = project(extra=extra)
    assert projected is original


def test_unknown_production_withholds_projection():
    projected, original = project(production=b'def safe_divide(a, b):\n    return callback(a, b)\n')
    assert projected is original


def test_normalized_crlf_spans_preserve_whole_oracle():
    projected, _ = project(BEFORE.replace('\n', '\r\n'))
    oracle = projected.units[0].side.assertions[0]
    assert oracle.text == BEFORE[slice(*oracle.span)]
