"""Pytest's request parameter never gains imported-callable authority."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def request(value):\n    return value\n'
PREFIX = 'import pytest\nfrom app.prod import request\n'
SHADOW = PREFIX + '@pytest.fixture(params=[("unused",)])\ndef subject(request):\n    return request\n'
IMPORTED = PREFIX + '@pytest.fixture\ndef subject():\n    return request\n'
NATIVE = 'def test_value(subject):\n    assert subject("okay") == "okay"\n'
DECORATED = ('@pytest.mark.parametrize("value", ["okay"])\n'
             'def test_value(subject,value):\n    assert subject(value) == "okay"\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


@pytest.mark.parametrize('consumer', [NATIVE, DECORATED])
@pytest.mark.parametrize('reverse', [False, True])
def test_fixture_request_and_imported_function_are_not_equivalent(consumer, reverse):
    before, after = SHADOW + consumer, IMPORTED + consumer
    if reverse:
        before, after = after, before
    assert not projected(run(before, after, PRODUCTION)[0])


@pytest.mark.parametrize('consumer', [NATIVE, DECORATED])
def test_prefix_call_cannot_use_a_shadowed_import(consumer):
    before = SHADOW.replace('    return request', '    assert request("okay") == "okay"\n    return request') + consumer
    after = IMPORTED.replace('    return request', '    assert request("okay") == "okay"\n    return request') + consumer
    assert not projected(run(before, after, PRODUCTION)[0])


def test_consumer_parameter_named_like_import_does_not_change_callee_resolution():
    before = IMPORTED + NATIVE
    after = IMPORTED + ('@pytest.mark.parametrize("request", ["okay"])\n'
                        'def test_value(subject,request):\n    assert subject(request) == "okay"\n')
    assert not projected(run(before, after, PRODUCTION)[0])


def test_plain_fixture_still_returns_the_real_imported_request_function():
    ir, findings, verdict = run(PREFIX + 'def test_value():\n    assert request("okay") == "okay"\n',
                               IMPORTED + NATIVE, PRODUCTION)
    assert projected(ir) and verdict == 'pass' and not findings
