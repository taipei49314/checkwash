"""Local clone checks never substitute for real production coverage."""
import ast

import pytest

from test_issue_expectation_families import run

PRODUCTION = ('def strip_prefix(s,prefix):\n    if s.startswith(prefix):\n'
              '        return s[len(prefix):]\n    return s\n')
BEFORE = '''from app.prod import strip_prefix
def test_hit():
    assert strip_prefix("foobar","foo") == "bar"
def test_miss():
    assert strip_prefix("foobar","baz") == "foobar"
def test_empty():
    assert strip_prefix("ab","") == "ab"
'''
HELPER = '''def local_strip(s,prefix):
    if s.startswith(prefix):
        return s[len(prefix):]
    return s
'''
AFTER = ('''from app.prod import strip_prefix
import pytest
@pytest.fixture
def cases():
    return [("foobar","foo","bar"),("foobar","baz","foobar"),("ab","","ab")]
''' + HELPER + '''def test_hit(cases):
    for s,prefix,expected in cases:
        assert strip_prefix(s,prefix) == expected
def test_miss(cases):
    for s,prefix,expected in cases:
        assert local_strip(s,prefix) == expected
def test_empty(cases):
    for s,prefix,expected in cases:
        assert strip_prefix(s,prefix) == expected
''')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def without(source, names):
    tree=ast.parse(source)
    tree.body=[node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name not in names]
    return ast.unparse(tree)


def test_added_local_checks_remain_separate_from_all_original_production_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    units=ir.files[0].units
    assert sum(unit.before is not None and unit.after is not None for unit in units if unit.qualname.startswith('test_concrete')) == 3
    auxiliary=[unit for unit in units if unit.qualname.startswith('test_local_auxiliary')]
    assert len(auxiliary) == 3
    assert all(unit.before is None and len(unit.after.assertions) == 1 for unit in auxiliary)
    assert all('local_strip' in unit.after.assertions[0].left for unit in auxiliary)


def test_clone_coverage_cannot_replace_one_missing_production_input():
    after=AFTER.replace('("ab","","ab")','') + '\ndef test_local_only():\n    assert local_strip("ab","") == "ab"\n'
    assert not projected(run(BEFORE,after,PRODUCTION)[0])


def test_clone_coverage_cannot_replace_all_real_production_consumers():
    assert not projected(run(BEFORE,without(AFTER,{'test_hit','test_empty'}),PRODUCTION)[0])


def test_changed_real_expected_value_still_blocks_beside_local_checks():
    _, findings, verdict=run(BEFORE,AFTER.replace('("foobar","foo","bar")','("foobar","foo","wrong")'),PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change',[
    ('return s[len(prefix):]', 'return "other"'),
    ('assert local_strip(s,prefix) == expected','assert local_strip(s,prefix) == "other"'),
    ('def test_miss(cases):','def test_miss_other(cases):'),
])
def test_existing_auxiliary_definition_or_check_identity_is_preserved(change):
    # A caller rename keeps the same checked obligations; definition/answer edits do not.
    ir, _, _=run(AFTER,AFTER.replace(*change),PRODUCTION)
    if change[0].startswith('def test_miss'):
        assert projected(ir)
    else:
        assert not projected(ir)


def test_preexisting_auxiliary_checks_cannot_disappear():
    after=without(AFTER,{'test_miss','local_strip'})
    assert not projected(run(AFTER,after,PRODUCTION)[0])


def test_preexisting_auxiliary_multiplicity_cannot_shrink():
    duplicate='\ndef test_again():\n    assert local_strip("ab","") == "ab"\n'
    assert not projected(run(AFTER+duplicate,AFTER,PRODUCTION)[0])


@pytest.mark.parametrize('change',[
    ('return s[len(prefix):]', 'globals()["strip_prefix"] = replacement\n        return s[len(prefix):]'),
    ('return s[len(prefix):]', 'mutate()\n        return s[len(prefix):]'),
    ('return s[len(prefix):]', 'return external(s,prefix)'),
    ('def local_strip(s,prefix):','@decorate\ndef local_strip(s,prefix):'),
    ('def local_strip(s,prefix):','def local_strip(s,prefix=callback()):'),
    ('def local_strip(s,prefix):','def local_strip(s,prefix) -> callback():'),
    ('def test_miss(cases):','@pytest.mark.skip\ndef test_miss(cases):'),
    ('def test_miss(cases):','def test_miss(cases,other):'),
    ('def test_miss(cases):','def test_hit(cases):'),
    ('assert local_strip(s,prefix) == expected','assert local_strip(s,s) == expected'),
    ('assert local_strip(s,prefix) == expected','assert local_strip(s,prefix) == expected, callback()'),
    ('assert local_strip(s,prefix) == expected','local_strip(s,prefix) == expected'),
    ('for s,prefix,expected in cases:', 'for local_strip,prefix,expected in cases:'),
    ('@pytest.fixture\n','@pytest.fixture(scope="module")\n'),
    ('("foobar","foo","bar")','(["foobar"],"foo","bar")'),
    ('from app.prod import strip_prefix','from app.prod import strip_prefix\nimport mutator'),
    ('def test_hit(cases):','alias = local_strip\ndef test_hit(cases):'),
    ('def test_hit(cases):','local_strip = replacement\ndef test_hit(cases):'),
    ('def test_hit(cases):','len = replacement\ndef test_hit(cases):'),
])
def test_unproved_local_binding_side_effect_or_caller_has_no_projection(change):
    assert not projected(run(BEFORE,AFTER.replace(*change),PRODUCTION)[0])


@pytest.mark.parametrize('production',[
    'import mutator\n'+PRODUCTION,
    'def strip_prefix(s,prefix):\n    from tests.test_case import local_strip\n    return local_strip(s,prefix)\n',
    'def strip_prefix(s,prefix):\n    return external(s,prefix)\n',
    'def strip_prefix(s,prefix):\n    return globals()["answer"]\n',
])
def test_earlier_production_cannot_change_local_checks(production):
    assert not projected(run(BEFORE,AFTER,production)[0])


def test_autouse_execution_context_is_still_required():
    context={'conftest.py':b'import pytest\n@pytest.fixture(autouse=True)\ndef mutate():\n    callback()\n'}
    assert not projected(run(BEFORE,AFTER,PRODUCTION,context=context)[0])
