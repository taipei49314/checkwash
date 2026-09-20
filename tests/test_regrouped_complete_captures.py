"""Split fragments earn credit only after every complete oracle is retained."""
import pytest

from test_issue_expectation_families import run
from test_sequential_captured_oracles import projected


STRING = ('def subject(value):\n    return value.strip()\n', 'got = subject(" Ada ")',
          ['assert len(got) == 3', 'assert got.startswith("A")', 'assert got == "Ada"'])
MEMBERSHIP = (STRING[0], STRING[1], ['assert "  " not in got', 'assert "A" in got', 'assert got == "Ada"'])
TUPLE = ('def subject(value):\n    return (value, value + 1, value + 2)\n', 'a, b, c = subject(1)',
         ['assert a == 1', 'assert b == 2', 'assert c == 3'])
FIELDS = ('def subject(value):\n    return {"first": value, "last": value + "!"}\n', 'got = subject("Ada")',
          ['assert got["first"] == "Ada"', 'assert got["last"] == "Ada!"'])


def sources(shape, *, message=''):
    production, capture, checks = shape
    before = 'from app.prod import subject\ndef test_value():\n    ' + '\n    '.join([capture, *checks]) + '\n'
    after = 'from app.prod import subject\ndef test_value():\n    ' + '\n    '.join([capture, *checks[:-1]])
    after += '\ndef test_tail():\n    ' + capture + '\n    ' + checks[-1] + message + '\n'
    return before, after, production


@pytest.mark.parametrize('shape', [STRING, MEMBERSHIP, TUPLE, FIELDS])
@pytest.mark.parametrize('message', ['', ', "regression"', ', "expected " + repr(3)'])
def test_split_clauses_retain_the_complete_original_obligation(shape, message):
    before, after, production = sources(shape, message=message)
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


def test_fresh_expected_binding_and_local_renames_can_compose_with_tuple_fragments():
    before, after, production = sources(TUPLE)
    after = after.replace('a, b, c = subject(1)', 'red, green, blue = subject(1)').replace('assert a ==', 'assert red ==').replace('assert b ==', 'assert green ==')
    after = after.replace('assert c == 3', 'expected = 3\n    assert blue == expected')
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('edit', [
    lambda text: text.replace('    assert got.startswith("A")\n', ''),
    lambda text: text.replace('    assert len(got) == 3\n', ''),
    lambda text: text.replace('    assert got == "Ada"\n', ''),
    lambda text: text.replace('    assert got.startswith("A")', '    assert len(got) == 3\n    assert got.startswith("A")'),
    lambda text: text.replace('assert got.startswith("A")', 'assert got.startswith("B")'),
    lambda text: text.replace('    assert got == "Ada"', '    alias = got\n    assert alias == "Ada"'),
    lambda text: text.replace('    assert got == "Ada"', '    mutate(got)\n    assert got == "Ada"'),
    lambda text: text.replace('subject(" Ada ")', 'subject(custom)'),
    lambda text: text.replace('assert got == "Ada"', 'assert got == "Ada", callback()'),
    lambda text: text.replace('assert got == "Ada"', 'assert got == "Ada", "text" + repr(callback())'),
    lambda text: text.replace('def test_tail():', '@decorator\ndef test_tail():'),
    lambda text: text.replace('def test_tail():', 'def test_tail(request):'),
    lambda text: text + '\ndef test_explicit():\n    test_value()\n',
    lambda text: text + '\nalias = test_value\n',
    lambda text: text + '\ndef test_tail():\n    assert True\n',
    lambda text: text.replace('def test_tail():', 'def test_tail():\n    return'),
])
def test_partial_missing_duplicated_or_runtime_controlled_clauses_get_no_credit(edit):
    before, after, production = sources(STRING)
    ir, _, _ = run(before, edit(after), production)
    assert not projected(ir)


def test_duplicate_original_complete_checks_cannot_be_collapsed():
    before, after, production = sources(STRING)
    before += '\ndef test_repeated():' + before.split('def test_value():', 1)[1]
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


def test_different_original_answers_for_one_input_cannot_be_deduplicated():
    before, after, production = sources(TUPLE)
    before += '\ndef test_contradiction():' + before.split('def test_value():', 1)[1].replace('assert c == 3', 'assert c == 0')
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


@pytest.mark.parametrize('change', ['remove', 'replace', 'duplicate-count'])
def test_entailed_membership_clauses_still_keep_their_original_identity_and_multiplicity(change):
    before, after, production = sources(MEMBERSHIP)
    if change == 'remove':
        after = after.replace('    assert "A" in got\n', '')
    elif change == 'replace':
        after = after.replace('assert "A" in got', 'assert "da" in got')
    else:
        before = before.replace('    assert "A" in got', '    assert "A" in got\n    assert "A" in got')
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


def test_unchanged_duplicate_memberships_remain_counted_individually():
    before, after, production = sources(MEMBERSHIP)
    before = before.replace('    assert "A" in got', '    assert "A" in got\n    assert "A" in got')
    after = after.replace('    assert "A" in got', '    assert "A" in got\n    assert "A" in got')
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


def test_complete_but_rewritten_tuple_answer_still_blocks():
    before, after, production = sources(TUPLE)
    ir, findings, verdict = run(before, after.replace('assert c == 3', 'assert c == 0'), production)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'def subject(value):\n    global seen\n    seen = value\n    return value.strip()\n',
    'def subject(value):\n    return callback(value)\n',
    'def subject(value):\n    from tests.test_case import test_tail\n    return value.strip()\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef subject(value):\n    return Value()\n',
])
def test_repeated_calls_require_closed_pure_primitive_source(production):
    before, after, _ = sources(STRING)
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'callback()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-x\n'},
])
def test_regrouped_failure_barriers_require_inert_default_execution(context):
    before, after, production = sources(STRING)
    ir, _, _ = run(before, after, production, context=context)
    assert not projected(ir)


@pytest.mark.parametrize('binding', ['def repr(value):\n    return callback(value)\n', 'from external import repr\n', 'repr = "masked"\n'])
def test_removed_literal_repr_messages_still_require_unshadowed_authority(binding):
    before, after, production = sources(TUPLE, message=', "expected " + repr(3)')
    ir, _, _ = run(before, after + '\n' + binding, production)
    assert not projected(ir)


@pytest.mark.parametrize('name', ['_checkwash_capture_0', '_checkwash_capture_1'])
def test_generated_capture_names_cannot_bind_preexisting_unbound_reads(name):
    before, after, production = sources(TUPLE)
    after = after.replace('assert c == 3', 'assert ' + name + ' == 3')
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


def test_generated_string_capture_name_cannot_bind_an_unrelated_read():
    before, after, production = sources(STRING)
    after = after.replace('assert got == "Ada"', 'assert _checkwash_capture_0 == "Ada"')
    ir, _, _ = run(before, after, production)
    assert not projected(ir)


def test_existing_cross_block_capture_alias_keeps_its_actual_binding():
    before, after, production = sources(STRING)
    prefix = '''def test_other():
    _checkwash_capture_0 = subject(" Bob ")
    assert len(_checkwash_capture_0) == 3
    assert _checkwash_capture_0.startswith("B")
    assert _checkwash_capture_0 == "Bob"
'''
    before += '\n' + prefix
    after = after.replace('assert got == "Ada"', 'assert _checkwash_capture_0 == "Ada"') + '\n' + prefix
    ir, _, _ = run(before, after, production)
    assert not projected(ir)
