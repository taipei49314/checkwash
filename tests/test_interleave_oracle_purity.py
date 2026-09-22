"""Whole-source interleave proof admits only a fresh local result list."""
import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_issue_expectation_families import run


PRODUCTION = ('def interleave(a,b):\n    out = []\n    n = max(len(a),len(b))\n    for i in range(n):\n'
              '        if i < len(a):\n            out.append(a[i])\n'
              '        if i < len(b):\n            out.append(b[i])\n    return out\n')
BEFORE = ('from app.prod import interleave\ndef test_equal():\n'
          '    assert interleave([1,2],["a","b"]) == [1,"a",2,"b"]\n'
          'def test_uneven():\n    assert interleave([1,2,3],["a"]) == [1,"a",2,3]\n')
AFTER = ('import pytest\nfrom app.prod import interleave\n'
         '@pytest.fixture(params=[([1,2],["a","b"],[1,"a",2,"b"]),([1,2,3],["a"],[1,"a",2,3])])\n'
         'def cases(request):\n    return request.param\n'
         'def check(a,b,expected):\n    result = interleave(a,b)\n'
         '    assert result == expected, f"Expected {expected}, got {result}"\n'
         'def test_cases(cases):\n    a,b,expected = cases\n    check(a,b,expected)\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_closed_interleave_retains_helper_capture_and_diagnostic_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert sum(unit.before is not None and unit.after is not None for unit in ir.files[0].units) == 2


def test_changed_expected_value_remains_blocking():
    _, findings, verdict = run(BEFORE, AFTER.replace('[1,"a",2,3]', '[1,"a",2,4]'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('out = []', 'out = a'),
    ('out = []', 'out = shared'),
    ('out.append(a[i])', 'a.append(a[i])'),
    ('out.append(a[i])', 'out.append(callback(a[i]))'),
    ('out.append(a[i])', 'out.append(a.pop())'),
    ('out.append(a[i])', 'out.append(b[i])'),
    ('max(len(a),len(b))', 'callback(a,b)'),
    ('    return out', '    mutate(a)\n    return out'),
    ('    return out', '    return Custom(out)'),
    ('for i in range(n):', 'for i in external(n):'),
    ('if i < len(a):', 'if callback(a):'),
    ('def interleave(a,b):', 'def interleave(a,b=callback()):'),
    ('def interleave(a,b):', '@decorator\ndef interleave(a,b):'),
])
def test_incomplete_or_effectful_loop_has_no_source_proof(change):
    source = PRODUCTION.replace(*change)
    assert not _pure_module(source.encode(), 'interleave')
    assert not projected(run(BEFORE, AFTER, source)[0])


@pytest.mark.parametrize('source', [
    'import mutator\n' + PRODUCTION,
    'max = callback\n' + PRODUCTION,
    'def len(value):\n    return 1\n' + PRODUCTION,
    PRODUCTION + '\ninterleave.__code__ = callback.__code__\n',
])
def test_entire_module_and_builtin_bindings_remain_part_of_the_proof(source):
    assert not projected(run(BEFORE, AFTER, source)[0])


@pytest.mark.parametrize('message', ['f"{callback(result)}"', 'f"{result!r:custom}"', 'format(result)'])
def test_arbitrary_diagnostic_callbacks_do_not_get_hidden(message):
    after = AFTER.replace('f"Expected {expected}, got {result}"', message)
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_local_names_can_change_without_changing_the_whole_body_grammar():
    source = PRODUCTION.replace('out', 'values').replace('for i in', 'for index in').replace('if i <', 'if index <').replace('[i]', '[index]')
    assert _pure_module(source.encode(), 'interleave')
    assert run(BEFORE, AFTER, source)[2] == 'pass'


@pytest.mark.parametrize('old,new', [('out', 'a'), ('out', 'range'), ('n', 'len'), ('i', 'max')])
def test_local_aliases_cannot_capture_inputs_or_builtin_authority(old, new):
    import re
    source = re.sub(r'\b' + old + r'\b', new, PRODUCTION)
    assert not _pure_module(source.encode(), 'interleave')
