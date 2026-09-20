"""Literal component answers survive a closed hexadecimal tuple helper."""
import pytest

from checkwash.frontends.python import table_oracles
from test_issue_expectation_families import run

PRODUCTION = '''def parse_hex_rgb(s):
    s = s.lstrip("#")
    return int(s[0], 16), int(s[1], 16), int(s[2], 16)
'''
BEFORE = '''from app.prod import parse_hex_rgb
def test_white():
    r, g, b = parse_hex_rgb("#ffffff")
    assert r == 255
    assert g == 255
    assert b == 255
def test_red():
    r, g, b = parse_hex_rgb("ff0000")
    assert r == 255
    assert g == 0
    assert b == 0
'''
HELPER = '''def expected_rgb(hex_str):
    s = hex_str.lstrip("#")
    return int(s[0], 16), int(s[1], 16), int(s[2], 16)
'''
AFTER = '''from app.prod import parse_hex_rgb
import pytest
''' + HELPER + '''def test_white():
    r, g, b = parse_hex_rgb("#ffffff")
    assert r == expected_rgb("#ffffff")[0]
    assert g == expected_rgb("#ffffff")[1]
    assert b == expected_rgb("#ffffff")[2]
def test_red():
    r, g, b = parse_hex_rgb("ff0000")
    assert r == expected_rgb("ff0000")[0]
    assert g == expected_rgb("ff0000")[1]
    assert b == expected_rgb("ff0000")[2]
def test_invalid_hex():
    with pytest.raises(ValueError):
        parse_hex_rgb("gbcdef")
'''


def corrected(source):
    for index, bounds in [(0, '0:2'), (1, '2:4'), (2, '4:6')]:
        source = source.replace(f's[{index}]', f's[{bounds}]')
    return source


def projected(source):
    module = table_oracles._module(source.encode(), baseline=False)
    return module is not None and any(form == 'hex-tuple-answer' for _, form in module[6])


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('expected_rgb', 'answer'),
    AFTER.replace('hex_str', 'text'),
    AFTER.replace('s =', 'text =').replace('int(s[', 'int(text['),
    AFTER.replace(')[2]', ')[-1]'),
])
def test_whole_tuple_answers_remain_visible_to_existing_expected_detector(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(after) and result[2] == 'block'
    assert len([f for f in result[1] if f.rule == 'EXPECTED_VALUE_CHANGED']) == 2
    assert any(u.qualname.startswith('test_exception_') for u in result[0].files[0].units)


def test_correct_helper_keeps_good_and_bad_production_oracles():
    after = corrected(AFTER)
    for production in (PRODUCTION, corrected(PRODUCTION)):
        assert run(BEFORE, after, production)[2] == 'pass'


@pytest.mark.parametrize('old,new', [
    ('def expected_rgb(hex_str):', 'def expected_rgb(int):'),
    ('hex_str', '__debug__'),
    ('hex_str', 'parse_hex_rgb'),
    ('hex_str', 'pytest'),
    ('s =', 'int ='),
    ('s =', '__debug__ ='),
    ('s = hex_str.lstrip("#")', 's = callback(hex_str)'),
    ('hex_str.lstrip("#")','hex_str.strip("#")'),
    ('hex_str.lstrip("#")','hex_str.lstrip(chars="#")'),
    ('int(s[0], 16)','int(s[0], base=16)'),
    ('int(s[0], 16)','int(s[0], 10)'),
    ('int(s[0], 16)','int(s[0], 16, 10)'),
    ('int(s[0], 16)','int(callback(), 16)'),
    ('int(s[0], 16)','callback(s[0], 16)'),
    ('int(s[0], 16)','int(s[0], 16) if True else (int := 0)'),
    ('int(s[0], 16)','int(s[0], 16) if True else (yield 1)'),
    ('int(s[0], 16)','int(s[0], 16) if True else callback(x=1,x=2)'),
    ('int(s[2], 16)','int(s[999], 16)'),
    ('int(s[2], 16)','int(s[0:0], 16)'),
    ('int(s[2], 16)','int(s[::0], 16)'),
    ('int(s[0], 16), int(s[1], 16), int(s[2], 16)','[int(s[0],16),int(s[1],16),int(s[2],16)]'),
    ('    s =','    mutate()\n    s ='),
])
def test_helper_is_a_complete_closed_builtin_conversion(old,new):
    after = AFTER.replace(HELPER, HELPER.replace(old,new))
    assert not projected(after)


@pytest.mark.parametrize('after', [
    AFTER.replace('import pytest','from other import pytest'),
    AFTER.replace('import pytest','import pytest\nimport mutator'),
    AFTER.replace('from app.prod import parse_hex_rgb','from app.prod import parse_hex_rgb as int'),
    AFTER.replace('def test_white():','@pytest.mark.skip\ndef test_white():'),
    AFTER.replace('def test_white():','def test_white(expected_rgb):'),
    AFTER.replace('    r, g, b =','    assert False\n    r, g, b ='),
    AFTER.replace('r, g, b =','r, r, b ='),
    AFTER.replace('assert g ==','assert r =='),
    AFTER.replace('    assert g == expected_rgb("#ffffff")[1]\n',''),
    AFTER.replace('assert r == expected_rgb("#ffffff")[0]', 'assert r == expected_rgb("#ffffff")[0], "note"'),
    AFTER.replace('expected_rgb("#ffffff")', 'expected_rgb("ff0000")'),
    AFTER.replace('expected_rgb("#ffffff")[0]', 'expected_rgb(hex_str="#ffffff")[0]'),
    AFTER.replace('expected_rgb("#ffffff")[0]', 'expected_rgb("#ffffff")[99]'),
    AFTER.replace('expected_rgb("#ffffff")[0]', 'expected_rgb("#ffffff")[True]'),
    AFTER.replace('pytest.raises(ValueError)', 'pytest.raises(TypeError)'),
    AFTER.replace('pytest.raises(ValueError)', 'pytest.raises(ValueError, match="invalid")'),
    AFTER.replace('pytest.raises(ValueError):', 'pytest.raises(ValueError) as caught:'),
    AFTER.replace('parse_hex_rgb("gbcdef")','expected_rgb("gbcdef")'),
    AFTER + '\nexpected_rgb = other\n',
    AFTER + '\ndef test_other():\n    mutate()\n',
])
def test_whole_module_binding_and_each_component_are_retained(after):
    assert not projected(after)


def test_unused_return_component_must_also_convert_successfully():
    after = AFTER.replace(HELPER, HELPER.replace('int(s[2], 16)', 'int(s[2], 16), int(s[999], 16)'))
    assert not projected(after)


@pytest.mark.parametrize('context', [
    {'pytest.py':b''}, {'tests/pytest.py':b''}, {'app/__init__.py':b''},
    {'src/app/__init__.py':b'mutate()\n'},
    {'src/sitecustomize.py':b'import builtins\nbuiltins.int = custom\n'},
    {'tests/conftest.py':b'import builtins\nbuiltins.int = custom\n'},
    {'tests/test_other.py':b'import tests.test_case\ntests.test_case.expected_rgb = custom\n'},
    {'pytest.ini':b'[pytest]\ntestpaths=tests/other\n'},
])
def test_full_source_startup_and_builtin_authority_must_hold(context):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE,AFTER,PRODUCTION,context=context)[1])


@pytest.mark.parametrize('production', [
    'def parse_hex_rgb(s):\n    return Custom()\n',
    'def parse_hex_rgb(s):\n    mutate()\n    return (1,2,3)\n',
    'import builtins\nbuiltins.int = custom\n' + PRODUCTION,
    'from tests.test_case import expected_rgb\n' + PRODUCTION,
    PRODUCTION.replace('int(s[2], 16)', 'int(s[2], 16), 4'),
])
def test_primitive_production_tuple_arity_and_import_effects_are_proved(production):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE,AFTER,production)[1])


def test_source_span_points_to_original_component_assertion():
    result=run(BEFORE,AFTER,PRODUCTION)
    finding=next(f for f in result[1] if f.rule=='EXPECTED_VALUE_CHANGED')
    assert AFTER[slice(*finding.after.span)].startswith('assert r == expected_rgb(')


def test_input_only_edit_keeps_existing_ir_and_policy(monkeypatch):
    changed=AFTER.replace('"#ffffff"','"#aaffff"')
    actual=run(AFTER,changed,PRODUCTION)
    monkeypatch.setattr(table_oracles,'expand_hex_tuple_answers',lambda tree:set())
    assert actual==run(AFTER,changed,PRODUCTION)
