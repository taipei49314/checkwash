"""Tuple unpacking is equivalent only with a closed primitive tuple result."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = ('def parse_rgb(s):\n    s = s.lstrip("#")\n'
              '    return int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)\n')
BEFORE = ('from app.prod import parse_rgb\ndef test_white():\n'
          '    r,g,b = parse_rgb("#ffffff")\n    assert r == 255\n    assert g == 255\n    assert b == 255\n'
          'def test_red():\n    r,g,b = parse_rgb("ff0000")\n    assert r == 255\n    assert g == 0\n    assert b == 0\n')
AFTER = ('import pytest\nfrom app.prod import parse_rgb\n'
         '@pytest.fixture\ndef colors():\n    return [("#ffffff",(255,255,255)),("ff0000",(255,0,0)),("00ff00",(0,255,0))]\n'
         'def test_colors(colors):\n    for text,expected in colors:\n        r,g,b = parse_rgb(text)\n'
         '        assert (r,g,b) == expected\n'
         'def test_invalid():\n    with pytest.raises(ValueError):\n        parse_rgb("1g2r3b")\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_all_tuple_components_and_added_exception_are_preserved():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert sum(unit.before is not None and unit.after is not None for unit in ir.files[0].units) == 2
    assert any(unit.qualname.startswith('test_exception_') for unit in ir.files[0].units)


@pytest.mark.parametrize('value', ['(254,0,0)', '(255,1,0)', '(255,0,1)', '(255,0)', '(255,0,0,0)'])
def test_changed_component_or_arity_remains_an_expected_value_change(value):
    _, findings, verdict = run(BEFORE, AFTER.replace('(255,0,0)', value), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('assert (r,g,b)', 'assert (r,b,g)'),
    ('assert (r,g,b)', 'assert (r,g)'),
    ('r,g,b =', 'r,g,r ='),
    ('r,g,b =', 'r,*g,b ='),
    ('assert (r,g,b) == expected', 'assert (r,g,b) == expected, report()'),
    ('assert (r,g,b) == expected', 'assert r == expected'),
    ('        assert (r,g,b)', '        mutate()\n        assert (r,g,b)'),
])
def test_partial_reordered_or_effectful_tuple_checks_have_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('change', [
    ('    assert b == 255\n', ''),
    ('assert g == 255', 'assert b == 255'),
    ('assert g == 255', 'assert g == 255, report()'),
    ('    assert g == 255', '    mutate()\n    assert g == 255'),
])
def test_incomplete_original_components_do_not_invent_tuple_expectations(change):
    assert not projected(run(BEFORE.replace(*change), AFTER, PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('return int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)',
                       'return [int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)]'),
    PRODUCTION.replace('return int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)', 'return iter((1,2,3))'),
    'def parse_rgb(s):\n    return CustomTuple(s)\n',
    'import mutator\n' + PRODUCTION,
    PRODUCTION.replace('    s =', '    mutate()\n    s ='),
])
def test_non_tuple_or_unknown_runtime_result_has_no_projection(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_each_return_path_requires_the_same_tuple_arity():
    source = PRODUCTION.replace('    s =', '    if s == "bad":\n        return (1,2)\n    s =')
    assert not projected(run(BEFORE, AFTER, source)[0])
