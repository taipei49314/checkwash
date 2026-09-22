"""The branch predicate is the oracle in closed Boolean assert branches."""
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.frontend import parse_python


BEFORE = '''from app import increment
def test_increment():
    got = increment(3)
    if got == 4:
        assert True
    else:
        assert False, "incorrect increment"
'''


def compare(before, after):
    return analyze([FileChange('tests/test_increment.py', 'modified', before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21), root_reader={}.get)


def test_replacing_failed_branch_predicate_with_buggy_answer_blocks():
    after = 'from app import increment\ndef test_increment():\n    got = increment(3)\n    assert got == 2\n'
    ir, findings, verdict = compare(BEFORE, after)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)
    oracle = ir.files[0].units[0].before.assertions[0]
    assert oracle.left == 'got'
    assert oracle.right_value == '4'
    assert oracle.text.startswith('if got == 4:')


@pytest.mark.parametrize('condition,yes,no,direct', [
    ('value() == 4', 'True', 'False', 'value() == 4'),
    ('value() != 4', 'False', 'True', 'value() == 4'),
    ('value() is True', 'True', 'False', 'value() is True'),
    ('value() is not True', 'False', 'True', 'value() is True'),
])
def test_native_assert_refactor_keeps_one_oracle_and_polarity(condition, yes, no, direct):
    before = f'def test_value():\n    if {condition}:\n        assert {yes}\n    else:\n        assert {no}\n'
    after = f'def test_value():\n    assert {direct}\n'
    ir, findings, verdict = compare(before, after)
    assert findings == [] and verdict == 'pass'
    assert len(ir.files[0].units[0].before.assertions) == 1


@pytest.mark.parametrize('changed', [
    BEFORE.replace('assert True', 'assert observe()'),
    BEFORE.replace('assert True', 'observe()\n        assert True'),
    BEFORE.replace('"incorrect increment"', 'diagnostic()'),
    BEFORE.replace('assert False, "incorrect increment"', 'assert True'),
    BEFORE.replace('if got == 4:', 'if got < 4 < 10:'),
])
def test_effectful_or_nonexclusive_outcomes_are_not_projected(changed):
    parsed = parse_python(changed.encode(), collect_tests=True)
    assert not any(a.text.startswith('if ') for a in parsed.units[0].side.assertions)


def test_exception_constructor_shadow_does_not_affect_native_asserts():
    parsed = parse_python(('AssertionError = ValueError\n' + BEFORE).encode(), collect_tests=True)
    assert len(parsed.units[0].side.assertions) == 1
    assert parsed.units[0].side.assertions[0].right_value == '4'


def test_uncalled_nested_branch_is_not_counted():
    source = 'def test_value():\n    def helper():\n        if value() == 4:\n            assert True\n        else:\n            assert False\n    pass\n'
    assert not parse_python(source.encode(), collect_tests=True).units[0].side.assertions


def test_real_pytest_confirms_the_recorded_bug_was_hidden(tmp_path):
    import os
    import subprocess
    import sys

    (tmp_path / 'app.py').write_text('def increment(n):\n    return n - 1\n', encoding='utf-8')
    after = 'from app import increment\ndef test_increment():\n    got = increment(3)\n    assert got == 2\n'
    outcomes = []
    for source in (BEFORE, after):
        (tmp_path / 'test_increment.py').write_text(source, encoding='utf-8')
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'test_increment.py'],
                                cwd=tmp_path, capture_output=True, text=True, timeout=30,
                                env={**os.environ, 'PYTHONPATH': str(tmp_path), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
        outcomes.append(result.returncode)
    assert outcomes == [1, 0]
