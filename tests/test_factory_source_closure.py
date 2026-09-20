"""Factory projection must close production back-references and side effects."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.oracle_purity import pure_imported_calls
import ast


@pytest.mark.parametrize('source', [
    'def f(xs,n):\n    return [xs[i:i+n] for i in range(0,len(xs),n)]\n',
    'def f(path):\n    path = path.replace("\\\\", "/").rstrip("/")\n    if not path:\n        return ""\n    return path.rsplit("/",1)[-1]\n',
    'def f(n):\n    result = 1\n    for i in range(1,n+1):\n        result *= i\n    return result\n',
])
def test_closed_builtin_comprehensions_strings_and_scalar_accumulation(source):
    assert pure_imported_calls(b'from app import f\n', [ast.parse('f(1)', mode='eval').body],
                               path='tests/test_case.py', read={'app.py': source.encode()}.get)


@pytest.mark.parametrize('source', [
    'def f(n):\n    from tests.test_case import rows\n    return rows()[n]\n',
    'from tests.test_case import rows\ndef f(n):\n    return rows()[n]\n',
    'def f(n):\n    return globals()["rows"]()[n]\n',
    'def f(xs):\n    alias = xs\n    alias += [1]\n    return alias\n',
    'def f(xs):\n    result = 1\n    if xs:\n        result = xs\n    result *= 2\n    return result\n',
    'def f(xs):\n    result = 1\n    for i in range(2):\n        result = xs\n    result *= 2\n    return result\n',
    'def f(xs):\n    xs.append(1)\n    return xs\n',
    'def f(xs):\n    return xs.pop()\n',
    'def f(xs):\n    return xs.__class__\n',
    'def f(n):\n    range = external\n    return range(n)\n',
])
def test_calls_imports_reflection_and_mutable_accumulators_remain_unproved(source):
    assert not pure_imported_calls(b'from app import f\n', [ast.parse('f(1)', mode='eval').body],
                                   path='tests/test_case.py', read={'app.py': source.encode()}.get)


def test_factory_rewrite_cannot_hide_production_importing_an_unselected_row():
    before = '''from app import f
def rows():
    return [(1, 1), (0, 0)]
def check(value, expected):
    assert f(value) == expected
def test_value():
    check(*rows()[0])
'''
    after = before.replace('(0, 0)', '(1, 1)').replace('check(*rows()[0])', 'check(1, 1)')
    # Keep a referenced factory for a table carrier, without checking row1.
    after += '''def test_extra():
    check(*rows()[0])
'''
    sources = {'app.py': b'def f(value):\n    from tests.test_case import rows\n    return rows()[1][0]\n'}
    ir, _, _ = analyze([FileChange('tests/test_case.py', 'modified', before.encode(), after.encode())],
                       Config(), Contract(), [], datetime.date(2026, 9, 21),
                       root_reader=sources.get, root_searcher=lambda _: [])
    assert not any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)
