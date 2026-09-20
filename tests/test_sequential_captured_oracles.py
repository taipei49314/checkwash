"""Merged captures retain each complete primitive oracle block."""
import pytest

from test_issue_expectation_families import run


PROD = 'def label(value):\n    return value.strip()\n'
BLOCK = '''    got = label(" Ada ")
    assert len(got) == 3
    assert got.startswith("A")
    assert got == "Ada"
'''
SECOND = BLOCK.replace(' Ada ', ' Bob ').replace('"A"', '"B"').replace('"Ada"', '"Bob"')
BEFORE = 'from app.prod import label\ndef test_first():\n' + BLOCK + 'def test_second():\n' + SECOND
AFTER = BEFORE.replace('def test_second():\n', '')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('first,second,production', [
    (BLOCK, SECOND, PROD),
    (BLOCK.replace('assert len(got) == 3', 'assert "  " not in got').replace('assert got.startswith("A")', 'assert "A" in got'),
     SECOND.replace('assert len(got) == 3', 'assert "  " not in got').replace('assert got.startswith("B")', 'assert "B" in got'), PROD),
    ('    got = label("Ada")\n    assert got["first"] == "Ada"\n    assert got["last"] == ""\n',
     '    got = label("Bob")\n    assert got["first"] == "Bob"\n    assert got["last"] == ""\n',
     'def label(value):\n    return {"first": value, "last": ""}\n'),
])
@pytest.mark.parametrize('local', ['got', 'result'])
def test_complete_string_membership_and_dictionary_blocks_keep_every_oracle(first, second, production, local):
    before = 'from app.prod import label\ndef test_first():\n' + first + 'def test_second():\n' + second
    after = 'from app.prod import label\ndef test_first():\n' + first + second.replace('got', local)
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings
    assert len(ir.files[0].units) == 2


def test_changed_complete_expected_value_remains_detected():
    ir, findings, verdict = run(BEFORE, AFTER.replace('got == "Bob"', 'got == "B"'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('    assert got.startswith("B")\n', ''),
    AFTER.replace('    assert len(got) == 3\n', '', 1),
    AFTER.replace('    assert got == "Bob"\n', ''),
    AFTER.replace('    got = label(" Bob ")\n', ''),
    AFTER.replace('label(" Bob ")', 'label(got)'),
    AFTER.replace('label(" Bob ")', 'label(callback())'),
    AFTER.replace('    got = label(" Bob ")', '    alias = got\n    got = label(" Bob ")'),
    AFTER.replace('    got = label(" Bob ")', '    mutate(got)\n    got = label(" Bob ")'),
    AFTER.replace('    got = label(" Bob ")', '    label = other\n    got = label(" Bob ")'),
    AFTER.replace('assert got == "Bob"', 'assert got == "Bob", callback()'),
    AFTER.replace('    got = label(" Bob ")', '    return\n    got = label(" Bob ")'),
    AFTER.replace('def test_first():', '@decorate\ndef test_first():'),
])
def test_incomplete_blocks_aliases_and_runtime_effects_receive_no_projection(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


def test_deduplicating_equal_input_blocks_cannot_remove_an_obligation():
    before = BEFORE + 'def test_repeated():\n' + BLOCK
    ir, _, _ = run(before, AFTER, PROD)
    assert not projected(ir)


def test_merged_blocks_cannot_replace_a_same_file_len_helper_by_the_builtin():
    helper = '\ndef len(value):\n    assert value == value\n'
    before = AFTER + helper
    after = AFTER.replace('got', 'result') + helper
    ir, _, _ = run(before, after, PROD)
    assert not projected(ir)


def test_changing_one_field_remains_a_high_expectation_edit():
    block = '    got = label("Ada")\n    assert got["first"] == "Ada"\n    assert got["last"] == ""\n'
    before = 'from app.prod import label\ndef test_first():\n' + block + 'def test_second():\n' + block.replace('Ada', 'Bob')
    after = before.replace('def test_second():\n', '').replace('got["first"] == "Bob"', 'got["first"] == "Robert"')
    ir, findings, verdict = run(before, after, 'def label(value):\n    return {"first": value, "last": ""}\n')
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'def label(value):\n    return callback(value)\n',
    'def label(value):\n    global seen\n    seen = value\n    return value.strip()\n',
    'def label(value):\n    from tests.test_case import test_first\n    return value.strip()\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef label(value):\n    return Value()\n',
])
def test_complete_blocks_require_closed_primitive_side_effect_free_production(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'callback()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-x\n'},
])
def test_separate_test_failure_barriers_require_default_inert_context(context):
    ir, _, _ = run(BEFORE, AFTER, PROD, context=context)
    assert not projected(ir)
