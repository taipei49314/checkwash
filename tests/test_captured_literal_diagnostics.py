"""Inert literal diagnostics do not replace any complete captured check."""
import pytest

from test_issue_expectation_families import run
from test_sequential_captured_oracles import BEFORE, AFTER, PROD, projected


@pytest.mark.parametrize('clause', ['len(got) == 3', 'got.startswith("A")', 'got == "Ada"'])
@pytest.mark.parametrize('message', ['"regression"', '""', '"not the answer"'])
def test_complete_captured_blocks_accept_only_inert_literal_messages(clause, message):
    after = AFTER.replace('assert ' + clause, 'assert ' + clause + ', ' + message)
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('message', ['callback()', 'got', 'f"{got}"', 'str(got)', 'repr(got)',
                                     '"prefix" + callback()', '(mutate() or "text")'])
def test_dynamic_captured_messages_keep_their_original_evaluation(message):
    ir, _, _ = run(BEFORE, AFTER.replace('assert len(got) == 3', 'assert len(got) == 3, ' + message, 1), PROD)
    assert not projected(ir)


@pytest.mark.parametrize('clause', ['assert len(got) == 3', 'assert got.startswith("A")', 'assert got == "Ada"'])
def test_literal_messages_cannot_credit_an_incomplete_captured_block(clause):
    after = AFTER.replace('    ' + clause + '\n', '', 1).replace('assert got == "Bob"', 'assert got == "Bob", "message"')
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


def test_literal_message_does_not_hide_an_exact_answer_rewrite():
    after = AFTER.replace('assert got == "Bob"', 'assert got == "B", "regression"')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'def label(value):\n    return callback(value)\n',
    'def label(value):\n    global seen\n    seen = value\n    return value.strip()\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef label(value):\n    return Value()\n',
])
def test_diagnostics_do_not_relax_capture_source_purity(production):
    ir, _, _ = run(BEFORE, AFTER.replace('assert len(got) == 3', 'assert len(got) == 3, "message"', 1), production)
    assert not projected(ir)
