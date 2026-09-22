"""Only unshadowed representation of literal data can disappear as diagnostics."""
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
def test_combined():
    assert increment(1) == 2
    assert increment(2) == 3, "expected " + repr(3)
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('literal', ['3', '"answer"', '[1, 2]', '(None, True)', '{"answer": 3}', '{1, 2}'])
def test_literal_repr_diagnostic_preserves_complete_pure_oracles(literal):
    ir, findings, verdict = run(BEFORE, AFTER.replace('repr(3)', 'repr(' + literal + ')'), PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_actual_answer_edit_remains_a_high_finding_with_literal_repr_message():
    ir, findings, verdict = run(BEFORE, AFTER.replace('increment(2) == 3', 'increment(2) == 0'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('message', ['"expected " + repr(callback())', '"expected " + repr(actual)',
    '"expected " + repr(set())', '"expected " + repr(3, option=True)',
    '"expected " + str(3)', 'prefix + repr(3)', '"expected " * repr(3)',
    '"expected " + repr(*values)', '"expected " + repr([callback()])'])
def test_nonliteral_values_unknown_formatting_and_callbacks_decline(message):
    ir, _, _ = run(BEFORE, AFTER.replace('"expected " + repr(3)', message), PROD)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER + '\ndef repr(value):\n    assert value == value\n',
    AFTER.replace('from app.prod import increment', 'from app.prod import increment\nfrom external import repr'),
    AFTER.replace('from app.prod import increment', 'from app.prod import increment\nrepr = "masked"'),
    AFTER.replace('def test_combined():', 'def test_combined(repr):'),
    AFTER.replace('    assert increment(1)', '    repr = other\n    assert increment(1)'),
    AFTER.replace('def test_combined():', 'def test_combined():\n    def repr(value):\n        assert value == value'),
])
def test_module_parameter_and_local_bindings_cannot_mint_builtin_repr_authority(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    return callback(value)\n',
    'class Value:\n    def __repr__(self):\n        return callback()\ndef increment(value):\n    return Value()\n',
    'def increment(value):\n    import builtins\n    builtins.repr = callback\n    return value + 1\n',
])
def test_production_must_not_replace_format_authority_or_return_custom_objects(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)
