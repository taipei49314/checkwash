"""A closed helper row-unpack preserves all shared fixture consumers."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def fill_none(xs, default):\n    return [default if x is None else x for x in xs]\n'
BEFORE = ('from app.prod import fill_none\ndef test_middle():\n    assert fill_none([1,None,2],0) == [1,0,2]\n'
          'def test_only_none():\n    assert fill_none([None],0) == [0]\n'
          'def test_keeps_zero():\n    assert fill_none([0,1],9) == [0,1]\n')
AFTER = ('import pytest\nfrom app.prod import fill_none\n'
         '@pytest.fixture(params=[([1,None,2],0,[1,0,2]),([None],0,[0]),([0,1],9,[0,1])], ids=["middle","only_none","keeps_zero"])\n'
         'def input_data(request):\n    return request.param\n'
         'def check_result(row):\n    xs,default,expected = row\n    result = fill_none(xs,default)\n    assert result == expected\n'
         'def test_middle(input_data):\n    check_result(input_data)\n'
         'def test_only_none(input_data):\n    check_result(input_data)\n'
         'def test_keeps_zero(input_data):\n    check_result(input_data)\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_all_rows_and_consumers_keep_their_original_multiplicities():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    units = ir.files[0].units
    assert sum(unit.before is not None for unit in units) == 3
    assert sum(unit.after is not None for unit in units) == 9


def test_changed_original_expected_row_blocks():
    _, findings, verdict = run(BEFORE, AFTER.replace('([None],0,[0])', '([None],0,[1])'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('xs,default,expected = row', 'xs,default = row'),
    ('xs,default,expected = row', 'xs,*default,expected = row'),
    ('xs,default,expected = row', 'xs,default,xs = row'),
    ('xs,default,expected = row', 'xs,default,expected = callback(row)'),
    ('xs,default,expected = row', 'xs,default,expected = row\n    mutate(xs)'),
    ('result = fill_none(xs,default)', 'result = fill_none(row,default)'),
    ('result = fill_none(xs,default)', 'result = fill_none(xs,xs)'),
    ('def check_result(row):', '@decorator\ndef check_result(row):'),
    ('def check_result(row):', 'def check_result(row=callback()):'),
    ('    check_result(input_data)', '    check_result(input_data, input_data)'),
    ('    check_result(input_data)', '    check_result = callback\n    check_result(input_data)'),
    ('    check_result(input_data)', '    check_result(input_data)\n    mutate()'),
])
def test_unknown_unpack_alias_dispatch_or_side_effect_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('ids', [
    'callback', '["middle"]', '["same","same","same"]', '["middle",callback(),"zero"]',
    '["middle",0,"zero"]', 'None',
])
def test_only_exact_literal_ids_are_inert_collection_metadata(ids):
    after = AFTER.replace('["middle","only_none","keeps_zero"]', ids)
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'def fill_none(xs,default):\n    xs.append(default)\n    return xs\n',
    'def fill_none(xs,default):\n    return xs\n',
    'def fill_none(xs,default):\n    return [callback(x) for x in xs]\n',
    'def fill_none(xs,default):\n    return [default if not x else x for x in xs]\n',
    PRODUCTION + 'fill_none = external\n',
    'import mutator\n' + PRODUCTION,
])
def test_shared_mutable_inputs_need_complete_fill_none_source_proof(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_live_original_row_reference_cannot_resolve_to_a_module_constant():
    after = AFTER.replace('def input_data(request):', 'def input_data(request):')
    after = after.replace('import pytest\n', 'import pytest\nrow = (1,2,3)\n').replace('fill_none(xs,default)', 'fill_none(row,default)')
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_unaccounted_extra_helper_reference_has_no_projection():
    after = AFTER + 'def test_extra():\n    check_result(([None],0,[0]))\n'
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_removed_consumer_multiplicity_is_not_treated_as_a_full_table():
    after = AFTER.replace('def test_keeps_zero(input_data):\n    check_result(input_data)\n', '')
    assert not projected(run(AFTER, after, PRODUCTION)[0])


@pytest.mark.parametrize('extra', [
    {'pytest.py': b'def fixture(f):\n    return f\n'},
    {'src/app/__init__.py': b'from mutator import callback\ncallback()\n'},
    {'conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef mutate():\n    callback()\n'},
])
def test_unknown_execution_context_stays_outside_the_proof(extra):
    assert not projected(run(BEFORE, AFTER, PRODUCTION, context=extra)[0])
