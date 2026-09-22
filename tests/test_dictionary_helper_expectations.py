"""Fixed dictionary field answers survive a closed whole-answer helper."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = '''def parse_name(s):
    parts = s.split()
    if len(parts) == 1:
        return {"first": parts[0], "last": ""}
    return {"first": parts[0], "last": parts[1]}
'''
BEFORE = '''from app.prod import parse_name
def test_simple():
    got = parse_name("Ada Lovelace")
    assert got["first"] == "Ada"
    assert got["last"] == "Lovelace"
def test_middle():
    got = parse_name("John Q Public")
    assert got["first"] == "John"
    assert got["last"] == "Public"
'''
AFTER = '''from app.prod import parse_name
def normalize_name(s):
    parts = s.split()
    return {"first": parts[0], "last": parts[1] if len(parts) > 1 else ""}
def test_simple():
    got = parse_name("Ada Lovelace")
    expected = normalize_name("Ada Lovelace")
    assert got == expected
def test_middle():
    got = parse_name("John Q Public")
    expected = normalize_name("John Q Public")
    assert got == expected
'''


def provenance(result):
    return [record for file in result[0].files for record in file.expected_provenance_events]


@pytest.mark.parametrize('after', [
    AFTER,
    AFTER.replace('got', 'actual').replace('expected', 'answer'),
    AFTER.replace('normalize_name(s)', 'normalize_name(value)').replace('s.split()', 'value.split()'),
    AFTER.replace('parts =', 'words =').replace('parts[', 'words[').replace('len(parts)', 'len(words)'),
    AFTER.replace('len(parts) > 1', 'len(parts) >= 2'),
    AFTER.replace('parts[1] if len(parts) > 1 else ""', 'parts[-2] if len(parts) > 2 else parts[-1]'),
])
def test_literal_field_answer_changed_by_closed_dictionary_helper_blocks(after):
    result = run(BEFORE, after, PRODUCTION)
    assert result[2] == 'block'
    records = provenance(result)
    assert len(records) == 1
    record = records[0]
    assert record[0] == 'test_middle'
    assert record[-4:] == ("parse_name('John Q Public')['last']", 'Eq', "'Public'", "'Q'")
    assert BEFORE[slice(*record[2])] == record[1]
    assert after[slice(*record[4])] == record[3]
    assert any(finding.rule == 'EXPECTATION_DEFINITION_CHANGED' for finding in result[1])


def test_honest_whole_dictionary_helper_keeps_each_field_answer():
    result = run(BEFORE, AFTER.replace('parts[1] if', 'parts[-1] if'), PRODUCTION)
    assert not provenance(result)
    assert not any(finding.rule == 'EXPECTATION_DEFINITION_CHANGED' for finding in result[1])
    assert result[2] == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('parse_name("John Q Public")', 'parse_name("John Public")'),
    AFTER.replace('parse_name("John Q Public")', 'other("John Q Public")'),
    AFTER.replace('parse_name("John Q Public")', 'parse_name(s="John Q Public")'),
    AFTER.replace('normalize_name("John Q Public")', 'normalize_name("John Public")'),
    AFTER.replace('normalize_name("John Q Public")', 'normalize_name(s="John Q Public")'),
    AFTER.replace('normalize_name("John Q Public")', 'normalize_name(callback())'),
    AFTER.replace('def test_middle():', 'def test_middle(parse_name):'),
    AFTER.replace('def test_middle():', '@pytest.mark.skip\ndef test_middle():'),
    AFTER.replace('test_middle', 'test_changed'),
    AFTER.replace('    got =', '    assert False\n    got ='),
    AFTER.replace('    got =', '    mutate()\n    got ='),
    AFTER.replace('assert got == expected', 'assert got is expected'),
    AFTER.replace('assert got == expected', 'assert got == expected, callback()'),
    AFTER.replace('expected = normalize_name', 'got = normalize_name'),
    AFTER.replace('expected = normalize_name', 'parse_name = normalize_name'),
    AFTER.replace('expected = normalize_name', 'normalize_name = normalize_name'),
    AFTER.replace('assert got == expected', 'assert expected == expected'),
    AFTER + '\ndef test_other():\n    mutate()\n',
    'import mutator\n' + AFTER,
])
def test_complete_same_input_consumption_and_unambiguous_local_binding_are_required(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('def normalize_name(s):', 'def normalize_name(s=callback()):'),
    AFTER.replace('def normalize_name(s):', '@decorate\ndef normalize_name(s):'),
    AFTER.replace('def normalize_name(s):', 'def normalize_name(s: callback()):'),
    AFTER.replace('def normalize_name(s):', 'def normalize_name(len):'),
    AFTER.replace('    parts =', '    mutate()\n    parts ='),
    AFTER.replace('parts = s.split()', 'parts = s.split(" ")'),
    AFTER.replace('parts = s.split()', 'parts = s.rsplit()'),
    AFTER.replace('parts = s.split()', 'parts = other.split()'),
    AFTER.replace('parts = s.split()', 'parts = callback(s)'),
    AFTER.replace('parts = s.split()', 'parts = s = s.split()'),
    AFTER.replace('parts = s.split()', 'len = s.split()'),
    AFTER.replace('parts[1] if', 'parts[99] if'),
    AFTER.replace('parts[1] if', 'external(parts) if'),
    AFTER.replace('parts[1] if', 'parts[1].strip() if'),
    AFTER.replace('parts[1] if', 'parts[1] + suffix if'),
    AFTER.replace('"first": parts[0], ', ''),
    AFTER.replace('"first": parts[0]', '"first": parts[0], "first": "other"'),
    AFTER.replace('"first": parts[0]', '"first": parts[0], "extra": "other"'),
    AFTER.replace('"first": parts[0]', 'key: parts[0]'),
    AFTER.replace('return {', 'yield {'),
])
def test_only_the_closed_primitive_split_helper_can_supply_a_whole_answer(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('before', [
    BEFORE.replace('assert got["first"] == "Ada"', 'assert got["first"] == "Ada", callback()'),
    BEFORE.replace('assert got["last"] == "Public"', 'assert got["first"] == "Public"'),
    BEFORE.replace('assert got["last"] == "Public"', 'assert got["last"] == expected()'),
    BEFORE.replace('got = parse_name', 'parse_name = parse_name'),
    BEFORE.replace('    got =', '    return\n    got ='),
    BEFORE + '\nparse_name = other\n',
    'import mutator\n' + BEFORE,
])
def test_original_field_inventory_must_be_complete_and_closed(before):
    assert not provenance(run(before, AFTER, PRODUCTION))


@pytest.mark.parametrize('production', [
    'def parse_name(s):\n    return Custom(s)\n',
    PRODUCTION.replace('parts = s.split()', 'mutate()\n    parts = s.split()'),
    PRODUCTION.replace('"last": parts[1]', '"other": parts[1]'),
    PRODUCTION.replace('"last": parts[1]', '"last": parts[1], "extra": "x"'),
    PRODUCTION.replace('return {"first": parts[0], "last": ""}', 'return None'),
    PRODUCTION.replace('    return {"first": parts[0], "last": parts[1]}', ''),
    'import mutator\n' + PRODUCTION,
    'from tests.test_case import normalize_name\n' + PRODUCTION,
])
def test_primitive_result_must_always_have_the_same_exact_dictionary_keys(production):
    assert not provenance(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('name', ['len', 'setup_module', 'setup_function', 'setUpModule', 'tearDownModule',
                                'pytestmark', 'pytest_plugins', 'pytest_generate_tests'])
def test_imported_control_names_withhold_dictionary_provenance(name):
    def alias(source):
        return source.replace('import parse_name', f'import parse_name as {name}').replace('got = parse_name(', f'got = {name}(')
    assert not provenance(run(alias(BEFORE), alias(AFTER), PRODUCTION))


@pytest.mark.parametrize('context', [
    {'app/__init__.py': b''}, {'app.py': b''}, {'tests/app/__init__.py': b''},
    {'pytest.py': b''}, {'src/app/__init__.py': b'mutate()\n'},
    {'tests/test_aaa.py': b'import app.prod\napp.prod.parse_name = lambda value: {}\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
])
def test_package_and_startup_authority_are_required_on_both_snapshots(context):
    assert not provenance(run(BEFORE, AFTER, PRODUCTION, context=context))
