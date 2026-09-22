"""A closed builtin empty length cannot retain a newly guarded assertion."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def is_success(code):\n    return code in (200, 201, 204)\n'
BEFORE = '''from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    assert is_success(201) == False
'''
AFTER = '''from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    if len([]):
        assert is_success(201) == False
'''


def assertions(before=BEFORE, after=AFTER, production=PRODUCTION, *, context=None):
    result = run(before, after, production, context=context)
    unit = next(unit for file in result[0].files for unit in file.units if unit.qualname == 'test_only_200')
    return result, unit.after.assertions


@pytest.mark.parametrize('empty', ['[]', '()', '{}', '""', 'b""'])
def test_known_builtin_empty_container_length_removes_only_its_unreachable_assertion(empty):
    result, retained = assertions(after=AFTER.replace('len([])', f'len({empty})'))
    assert result[2] == 'block'
    assert len(retained) == 1 and retained[0].text == 'assert is_success(200) == True'
    assert any(f.rule == 'ASSERT_REMOVED' and f.severity == 'high' for f in result[1])


def test_retained_assertion_text_and_span_stay_in_original_source():
    result, retained = assertions()
    original = result[0].files[0].units[0].before.assertions
    assert len(original) == 2
    assert AFTER[slice(*retained[0].span)] == retained[0].text
    assert retained[0].id == 'a0'


def test_a_live_assertion_after_the_disabled_one_keeps_its_original_span():
    after = AFTER.replace('    assert is_success(200) == True\n    if len([]):\n        assert is_success(201) == False',
                          '    if len([]):\n        assert is_success(200) == True\n    assert is_success(201) == False')
    _, retained = assertions(after=after)
    assert len(retained) == 1 and retained[0].id == 'a0'
    assert retained[0].text == 'assert is_success(201) == False'
    assert after[slice(*retained[0].span)] == retained[0].text


def test_a_disabled_only_oracle_still_blocks():
    before = BEFORE.replace('    assert is_success(200) == True\n', '')
    after = AFTER.replace('    assert is_success(200) == True\n', '')
    result, retained = assertions(before=before, after=after)
    assert result[2] == 'block' and not retained


@pytest.mark.parametrize('guard', ['len([1])', 'len((1,))', 'len({1: 2})', 'len("x")', 'len(b"x")',
    'len(value)', 'len(list())', 'len(tuple())', 'len(set())', 'len([callback()])', 'len(*values)',
    'len(obj=[])', 'len([], [])', 'other([])', 'builtins.len([])', 'len([]) == 0',
    'not len([])', 'flag and len([])', 'sys.version_info >= (99, 0)', 'sys.platform == "unknown"'])
def test_nonempty_unknown_dynamic_and_environment_guards_keep_ordinary_execution(guard):
    _, retained = assertions(after=AFTER.replace('len([])', guard))
    assert len(retained) == 2


@pytest.mark.parametrize('after', [
    AFTER.replace('def test_only_200():', 'def test_only_200(len):'),
    AFTER.replace('def test_only_200():', 'def test_only_200(len=custom):'),
    AFTER.replace('def test_only_200():', 'def test_only_200():\n    len = custom'),
    AFTER.replace('def test_only_200():', 'def test_only_200():\n    global len'),
    AFTER.replace('def test_only_200():', 'def test_only_200():\n    def len(value):\n        return 1'),
    AFTER.replace('def test_only_200():', 'def len(value):\n    return 1\ndef test_only_200():'),
    AFTER.replace('def test_only_200():', 'len = custom\ndef test_only_200():'),
    AFTER.replace('def test_only_200():', 'from external import len\ndef test_only_200():'),
    AFTER.replace('def test_only_200():', 'import builtins\nbuiltins.len = custom\ndef test_only_200():'),
    AFTER.replace('    if len([]):', '    mutate()\n    if len([]):'),
    AFTER.replace('    if len([]):', '    if (len := custom)([]):'),
    AFTER + '\nlen = custom\n',
    AFTER + '\ndef test_earlier():\n    mutate()\n',
])
def test_any_local_module_closure_or_callback_binding_prevents_builtin_authority(after):
    _, retained = assertions(after=after)
    assert len(retained) == 2


@pytest.mark.parametrize('after', [
    AFTER.replace('if len([]):', 'while len([]):'),
    AFTER + '    else:\n        assert is_success(201) == False\n',
    AFTER.replace('assert is_success(201) == False', 'assert is_success(202) == False'),
    AFTER.replace('assert is_success(201) == False', 'assert is_success(201) == True'),
    AFTER.replace('    assert is_success(200) == True\n', ''),
    AFTER.replace('        assert is_success(201) == False', '        check_result()'),
    AFTER.replace('        assert is_success(201) == False', '        value = is_success(201)\n        assert value == False'),
])
def test_unsupported_structural_changes_get_no_additional_dead_guard_proof(after):
    from checkwash.frontends.python.frontend import parse_python
    from checkwash.frontends.python.empty_length_guards import mark_empty_length_guards
    old, new = parse_python(BEFORE.encode(), True), parse_python(after.encode(), True)
    snapshot = {'src/app/__init__.py': b'', 'src/app/prod.py': PRODUCTION.encode(), 'tests/test_case.py': after.encode()}
    result = mark_empty_length_guards(BEFORE.encode(), after.encode(), old, new, path='tests/test_case.py',
        root_reader=snapshot.get, root_searcher=lambda needles: list(snapshot))
    assert result[0] is old and result[1] is new


@pytest.mark.parametrize('production', [
    'import builtins\nbuiltins.len = lambda value: 1\n' + PRODUCTION,
    'from tests.test_case import test_only_200\n' + PRODUCTION,
    'def len(value):\n    return 1\n' + PRODUCTION,
    'def is_success(code):\n    mutate()\n    return code == 200\n',
    'def is_success(code):\n    return Custom(code)\n',
])
def test_complete_production_source_cannot_rebind_builtin_or_return_unknown_values(production):
    assert len(assertions(production=production)[1]) == 2


@pytest.mark.parametrize('context', [
    {'app/__init__.py': b''}, {'app.py': b''}, {'tests/app/__init__.py': b''},
    {'pytest.py': b''}, {'src/pytest.py': b''}, {'tests/pytest.py': b''},
    {'src/app/__init__.py': b'import builtins\nbuiltins.len = lambda value: 1\n'},
    {'conftest.py': b'import builtins\nbuiltins.len = lambda value: 1\n'},
    {'tests/test_aaa.py': b'import builtins\nbuiltins.len = lambda value: 1\n'},
    {'pytest.ini': b'[pytest]\naddopts = -p mutator\n'},
])
def test_startup_siblings_and_competing_packages_withhold_the_optional_proof(context):
    assert len(assertions(context=context)[1]) == 2


def test_no_strict_reader_preserves_the_legacy_unknown_builtin_guard():
    from checkwash.frontends.python.frontend import parse_python
    from checkwash.frontends.python.empty_length_guards import mark_empty_length_guards
    old, new = parse_python(BEFORE.encode(), True), parse_python(AFTER.encode(), True)
    first, second = mark_empty_length_guards(BEFORE.encode(), AFTER.encode(), old, new, path='tests/test_case.py')
    assert first is old and second is new and len(second.units[0].side.assertions) == 2
