"""Fresh single-use literal expected variables do not erase concrete checks."""
import pytest

from test_issue_expectation_families import run


PROD = 'def increment(value):\n    return value + 1\n'
BEFORE = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_second():
    assert increment(2) == 3
'''
AFTER = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
    expected = 3
    assert increment(2) == expected
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_single_use_expected_local_preserves_merged_native_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_fresh_literal_container_expectation_remains_concrete():
    before = BEFORE.replace('increment(1) == 2', 'increment(1) == [2]').replace('increment(2) == 3', 'increment(2) == [3]')
    after = AFTER.replace('increment(1) == 2', 'increment(1) == [2]').replace('expected = 3', 'expected = [3]')
    ir, findings, verdict = run(before, after, 'def increment(value):\n    return [value + 1]\n')
    assert projected(ir) and verdict == 'pass' and not findings


def test_local_literal_answer_rewrite_is_still_a_high_finding():
    ir, findings, verdict = run(BEFORE, AFTER.replace('expected = 3', 'expected = 0'), PROD)
    assert not projected(ir) and verdict == 'block'
    assert any(f.severity == 'high' for f in findings)


def test_existing_local_expectation_carrier_keeps_ordinary_provenance():
    ir, findings, verdict = run(AFTER, AFTER.replace('expected = 3', 'expected = 0'), PROD)
    assert not projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTATION_DEFINITION_CHANGED' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('expected = 3', 'expected = callback()'),
    AFTER.replace('expected = 3', 'expected = other'),
    AFTER.replace('expected = 3', 'expected = 3\n    mutate()'),
    AFTER.replace('expected = 3', 'expected = 3\n    expected = 0'),
    AFTER + '    assert increment(2) == expected\n',
    AFTER.replace('increment(2) == expected', 'increment(expected) == expected'),
    AFTER.replace('increment(2) == expected', 'increment(2) == expected, callback(expected)'),
    AFTER.replace('expected', 'increment'),
    AFTER.replace('def test_first():', 'def test_first(expected):'),
    AFTER.replace('def test_first():', '@decorate\ndef test_first():'),
    AFTER.replace('expected = 3', 'expected = 3\n    del expected'),
    AFTER.replace('expected = 3', 'expected = alias = 3'),
    AFTER.replace('expected = 3', 'expected = 3\n    alias = expected'),
])
def test_rebindings_extra_uses_dynamic_values_and_authority_collisions_decline(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    return callback(value)\n',
    'def increment(value):\n    global answer\n    answer = value\n    return value + 1\n',
    'def increment(value):\n    from tests.test_case import test_first\n    return value + 1\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef increment(value):\n    return Value()\n',
])
def test_moving_literal_allocation_across_a_call_requires_closed_pure_source(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_dictionary_capture_and_single_use_literal_expectation_compose():
    before = '''from app.prod import names
def test_names():
    got = names("Ada")
    assert got["first"] == "Ada"
    assert got["last"] == ""
'''
    after = before.replace('    assert got["first"] == "Ada"', '    expected = "Ada"\n    assert got["first"] == expected')
    ir, findings, verdict = run(before, after, 'def names(value):\n    return {"first": value, "last": ""}\n')
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'callback()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-x\n'},
])
def test_literal_local_repair_requires_inert_collection_context(context):
    ir, _, _ = run(BEFORE, AFTER, PROD, context=context)
    assert not projected(ir)
