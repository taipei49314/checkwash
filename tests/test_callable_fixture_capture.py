"""Closed callable fixtures retain captured primitive results and setup checks."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app.squeeze import squeeze
def test_many():
    got = squeeze("a   b  c")
    assert "  " not in got
    assert " " in got
    assert got == "a b c"
def test_single():
    got = squeeze("x y")
    assert "  " not in got
    assert " " in got
    assert got == "x y"
'''
AFTER = '''from app.squeeze import squeeze
import pytest
@pytest.fixture
def subject():
    return squeeze
def test_many(subject):
    got = subject("a   b  c")
    assert got == "a b c"
def test_single(subject):
    got = subject("x y")
    assert got == "x y"
'''
PRODUCTION = 'def squeeze(value):\n    return " ".join(value.split())\n'


def run(after=AFTER, before=BEFORE, production=PRODUCTION, extra=None):
    sources = {'app/squeeze.py': production.encode(), **(extra or {})}
    return analyze([FileChange('tests/test_squeeze.py', 'modified', before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_zero_prefix_fixture_preserves_both_original_oracles():
    ir, findings, verdict = run()
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


def test_shared_capture_keeps_native_result_extraction_without_repeating_call():
    after = AFTER.replace('@pytest.fixture\ndef subject():\n    return squeeze\n', '').replace('(subject):', '():').replace('got = subject(', 'got = squeeze(')
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


def test_changed_expected_value_remains_high_after_capture():
    _, findings, verdict = run(AFTER.replace('assert got == "a b c"', 'assert got == "wrong"'))
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_fixture_prefix_assertion_is_retained_before_captured_consumer():
    before = 'from app.squeeze import squeeze\ndef test_values():\n    assert squeeze("a  b") == "a b"\n    assert squeeze("x y") == "x y"\n'
    after = '''from app.squeeze import squeeze
import pytest
@pytest.fixture
def subject():
    assert squeeze("a  b") == "a b"
    return squeeze
def test_values(subject):
    got = subject("x y")
    assert got == "x y"
'''
    ir, findings, verdict = run(after, before)
    assert projected(ir) and verdict == 'pass' and not findings
    changed = after.replace('assert squeeze("a  b") == "a b"', 'assert squeeze("a  b") == "wrong"')
    _, findings, verdict = run(changed, before)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('import pytest\n', ''),
    AFTER.replace('import pytest', 'import fake as pytest'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="module")'),
    AFTER.replace('@pytest.fixture', '@external\n@pytest.fixture'),
    AFTER.replace('def subject():', 'def subject(value=external()):'),
    AFTER.replace('return squeeze', 'squeeze.__code__ = external\n    return squeeze'),
    AFTER.replace('return squeeze', 'return lambda value: value'),
    AFTER.replace('got = subject(', 'squeeze = subject(').replace('assert got ==', 'assert squeeze =='),
    AFTER.replace('got = subject(', 'subject = subject(').replace('assert got ==', 'assert subject =='),
    AFTER.replace('assert got == "x y"', 'assert got == got'),
    AFTER.replace('assert got == "x y"', 'assert got == "x y", external(got)'),
    AFTER.replace('got = subject("x y")', 'got = subject("x y")\n    mutate()'),
    AFTER + 'saved = subject\n',
    AFTER + 'subject.__wrapped__ = external\n',
])
def test_unknown_fixture_binding_lifecycle_and_aliases_withhold_capture_proof(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'class Result:\n    def __eq__(self, other):\n        return True\ndef squeeze(value):\n    return Result()\n',
    'def squeeze(value):\n    from tests.test_squeeze import subject\n    return subject(value)\n',
    'def squeeze(value):\n    return " ".join(external(value))\n',
    'def squeeze(value):\n    return value.split(callback())\n',
    'def squeeze(value):\n    globals()["squeeze"] = external\n    return value\n',
])
def test_string_capture_needs_closed_primitive_result_proof(production):
    ir, _, _ = run(production=production)
    assert not projected(ir)


def test_repository_pytest_shadow_cannot_provide_fixture_authority():
    ir, _, _ = run(extra={'pytest.py': b'def fixture(function):\n    return external\n'})
    assert not projected(ir)
