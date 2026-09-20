"""A fresh fixture loop must not replace the imported subject with local code."""
import ast
import pytest

from checkwash import engine
from test_issue_expectation_families import run

PRODUCTION = '''def percentage(part, total):
    if total == 0:
        return 0
    return int((part / total) * 100)
'''
BEFORE = '''from app.prod import percentage
def test_one_third():
    assert percentage(1, 3) == 33.33
'''
HELPER = '''def calculate_percentage(part, total):
    if total == 0:
        return 0
    return (part / total) * 100
'''
AFTER = '''import pytest
from app.prod import percentage
@pytest.fixture
def test_data():
    return [(1, 3, 33.33), (2, 4, 50.0), (1, 0, 0)]
''' + HELPER + '''
def test_percentage(test_data):
    for part, total, expected in test_data:
        result = calculate_percentage(part, total)
        assert round(result, 2) == expected, f"Expected {expected}, got {result} for part={part} and total={total}"
'''


def evidence(result):
    return result[0].globals.subject_installations


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('@pytest.fixture\n','@pytest.fixture()\n'),
    AFTER.replace('test_data','rows'), AFTER.replace('result','actual'),
    AFTER.replace('calculate_percentage','local_percentage'),
    AFTER.replace('f"Expected {expected}, got {result} for part={part} and total={total}"','"bad result"'),
    AFTER.replace('{result}', '{result!r}'),
    AFTER.replace('[(1, 3, 33.33), (2, 4, 50.0), (1, 0, 0)]', '[(1, 3, 33.33)]'),
])
def test_complete_fixture_loop_adds_existing_subject_installation_event(after):
    result = run(BEFORE, after, PRODUCTION)
    assert result[2] == 'block' and len(evidence(result)) == 1
    path, unit, target, text, span = evidence(result)[0]
    assert (path, unit, target) == ('tests/test_case.py','test_percentage','app.prod.percentage')
    assert after[slice(*span)] == text
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' and f.severity == 'high' for f in result[1])


def test_new_evidence_leaves_all_assertion_ir_and_alignment_unchanged(monkeypatch):
    current = run(BEFORE, AFTER, PRODUCTION)
    monkeypatch.setattr(engine,'fixture_local_implementation_events',lambda *a,**k:[])
    previous = run(BEFORE, AFTER, PRODUCTION)
    assert current[0].files == previous[0].files


@pytest.mark.parametrize('after', [
    AFTER.replace(HELPER, 'def calculate_percentage(part, total):\n    return percentage(part, total)\n'),
    AFTER.replace(HELPER, '').replace('import percentage', 'import percentage as calculate_percentage'),
    AFTER.replace('return (part / total) * 100', 'return round(percentage(part, total))'),
])
@pytest.mark.parametrize('production',[PRODUCTION, PRODUCTION.replace('int((part / total) * 100)','round((part / total) * 100, 2)')])
def test_forwarding_and_import_renaming_keep_the_original_provider(after,production):
    assert not evidence(run(BEFORE,after,production))


@pytest.mark.parametrize('after', [
    AFTER.replace('[(1, 3, 33.33), (2, 4, 50.0), (1, 0, 0)]','[]'),
    AFTER.replace('(1, 3, 33.33)', '(2, 3, 33.33)'),
    AFTER.replace('(1, 3, 33.33)', '(1, 3, 33.0)'),
    AFTER.replace('(1, 3, 33.33), (2, 4, 50.0)', '(2, 4, 50.0), (1, 3, 33.33)'),
    AFTER.replace('(2, 4, 50.0)', '(callback(), 4, 50.0)'),
    AFTER.replace('(2, 4, 50.0)', '(True, 4, 50.0)'),
    AFTER.replace('(2, 4, 50.0)', '(2, 4, 1e999)'),
    AFTER.replace('(2, 4, 50.0)', '(2, 4)'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(scope="module")\n'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(autouse=True)\n'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(params=[1])\n'),
    AFTER.replace('test_data','request'),
    AFTER.replace('def test_data():', 'def test_data(other):'),
    AFTER.replace('    return [(1, 3', '    mutate()\n    return [(1, 3'),
    AFTER.replace('    return [(1, 3', '    yield [(1, 3'),
    AFTER.replace('in test_data:', 'in callback(test_data):'),
    AFTER.replace('part, total, expected in test_data:', 'part, total, part in test_data:'),
    AFTER.replace('part, total, expected in test_data:', 'part, total, round in test_data:'),
    AFTER.replace('result = calculate_percentage(part, total)', 'result = calculate_percentage(total, part)'),
    AFTER.replace('result = calculate_percentage(part, total)', 'result = calculate_percentage(part, total=total)'),
    AFTER.replace('result = calculate_percentage(part, total)', 'expected = calculate_percentage(part, total)'),
    AFTER.replace('result = calculate_percentage(part, total)', 'round = calculate_percentage(part, total)'),
    AFTER.replace('result = calculate_percentage(part, total)', 'result = percentage(part, total)'),
    AFTER.replace('result = calculate_percentage(part, total)', 'result = other(part, total)'),
    AFTER.replace('        result =', '        assert False\n        result ='),
    AFTER.replace('        result =', '        test_data.clear()\n        result ='),
    AFTER.replace('round(result, 2)', 'round(result, 1)'),
    AFTER.replace('round(result, 2)', 'round(result, digits=2)'),
    AFTER.replace('round(result, 2)', 'other(result, 2)'),
    AFTER.replace('round(result, 2)', 'round(expected, 2)'),
    AFTER.replace('== expected', '== result'),
    AFTER.replace('== expected', 'is expected'),
    AFTER.replace('{result}', '{callback(result)}'),
    AFTER.replace('{result}', '{result:{callback()}}'),
    AFTER.replace('{result}', '{other}'),
    AFTER.replace('def test_percentage(test_data):', '@pytest.mark.skip\ndef test_percentage(test_data):'),
    AFTER.replace('def test_percentage(test_data):', 'def test_percentage(test_data, request):'),
    AFTER + '\ndef test_other(test_data):\n    test_data.clear()\n',
    AFTER + '\ncalculate_percentage = percentage\n',
])
def test_fixture_ownership_row_identity_and_primitive_consumer_are_required(after):
    assert not evidence(run(BEFORE,after,PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('return (part / total) * 100', 'return callback(part, total)'),
    AFTER.replace('return (part / total) * 100', 'return Custom()'),
    AFTER.replace('return (part / total) * 100', 'return part / (part - 2)'),
    AFTER.replace('return (part / total) * 100', 'return part / (part - 1)'),
    AFTER.replace('return 0\n', 'return callback()\n'),
    AFTER.replace('def calculate_percentage(part, total):', '@decorate\ndef calculate_percentage(part, total):'),
    AFTER.replace('def calculate_percentage(part, total):', 'def calculate_percentage(part, total=callback()):'),
    AFTER.replace('def calculate_percentage(part, total):', 'def calculate_percentage(round, total):'),
])
def test_helper_must_return_closed_numbers_on_every_fixture_row(after):
    assert not evidence(run(BEFORE,after,PRODUCTION))


@pytest.mark.parametrize('parameter', ['part', 'total'])
def test_uncompilable_helper_parameter_cannot_supply_replacement_execution(parameter):
    after = AFTER.replace(HELPER, HELPER.replace(parameter, '__debug__'))
    ast.parse(after)
    with pytest.raises(SyntaxError, match='__debug__'):
        compile(after, '<invalid-fixture-implementation>', 'exec')
    assert not evidence(run(BEFORE,after,PRODUCTION))


@pytest.mark.parametrize('parameter', ['part', 'total'])
def test_reserved_dunder_helper_parameters_have_no_closed_execution_proof(parameter):
    after = AFTER.replace(HELPER, HELPER.replace(parameter, '__value'))
    compile(after, '<reserved-parameter>', 'exec')
    assert not evidence(run(BEFORE,after,PRODUCTION))


@pytest.mark.parametrize('before', [BEFORE.replace('== 33.33','== 33.33, callback()'),
    BEFORE.replace('def test_one_third():','def test_one_third(request):'),
    BEFORE.replace('    assert percentage','    assert False\n    assert percentage'),
    BEFORE + '\ndef test_other():\n    assert percentage(2, 4) == 50\n',
])
def test_only_the_proved_original_oracle_is_matched(before):
    assert not evidence(run(before,AFTER,PRODUCTION))


@pytest.mark.parametrize('production', [
    'def percentage(part,total):\n    mutate()\n    return 0\n',
    'def percentage(part,total):\n    return Custom()\n',
    'import builtins\nbuiltins.round = custom\n' + PRODUCTION,
    'from tests.test_case import calculate_percentage\n' + PRODUCTION,
])
def test_complete_production_source_cannot_rebind_helper_or_builtins(production):
    assert not evidence(run(BEFORE,AFTER,production))


@pytest.mark.parametrize('context', [
    {'pytest.py':b''}, {'app/__init__.py':b''}, {'tests/app/__init__.py':b''},
    {'src/sitecustomize.py':b'import builtins\nbuiltins.round = custom\n'},
    {'tests/conftest.py':b'import pytest\n@pytest.fixture(autouse=True)\ndef modify():\n    mutate()\n'},
    {'src/app/__init__.py':b'mutate()\n'},
    {'tests/test_aaa.py':b'import tests.test_case\ntests.test_case.calculate_percentage = custom\n'},
])
def test_closed_startup_and_framework_authority_are_required(context):
    assert not evidence(run(BEFORE,AFTER,PRODUCTION,context=context))
