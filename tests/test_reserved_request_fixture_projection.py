"""The fixture function name request is reserved; request parameters are valid."""
import pytest

from test_issue_expectation_families import run


PROD = 'def increment(value):\n    return value + 1\n'
BEFORE = 'from app.prod import increment\ndef test_value():\n    assert increment(2) == 3\n'
PREFIX = 'from app.prod import increment\nimport pytest\n'


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('fixture,consumer', [
    ('@pytest.fixture\ndef request():\n    return 2\n',
     'def test_value(request):\n    assert increment(request) == 3\n'),
    ('@pytest.fixture()\ndef request():\n    return 2\n',
     'def test_value(request):\n    assert increment(request) == 3\n'),
    ('@pytest.fixture\ndef request():\n    return [(2, 3)]\n',
     'def test_value(request):\n    for value, expected in request:\n        assert increment(value) == expected\n'),
    ('@pytest.fixture(params=[(2, 3)])\ndef request(request):\n    return request.param\n',
     'def test_value(request):\n    value, expected = request\n    assert increment(value) == expected\n'),
    ('@pytest.fixture\ndef request():\n    return 2\n',
     'def test_value():\n    assert increment(2) == 3\n'),
])
def test_reserved_fixture_cannot_disappear_through_any_optional_projection(fixture, consumer):
    ir, _, _ = run(BEFORE, PREFIX + fixture + consumer, PROD)
    assert not projected(ir)


def test_normal_fixture_request_parameter_keeps_its_valid_role():
    after = PREFIX + '''@pytest.fixture(params=[(2, 3)])
def cases(request):
    return request.param
def test_value(cases):
    value, expected = cases
    assert increment(value) == expected
'''
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_ordinary_nonfixture_function_named_request_is_not_a_reserved_fixture():
    after = PREFIX + '''def request(actual, expected):
    assert actual == expected
def test_value():
    request(increment(2), 3)
'''
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings
