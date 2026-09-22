"""Pytest rejects a fixture named request before collecting any consumer."""
import pytest

from checkwash.frontends.python.expected_call_authority import safe_call_graph
from test_issue_expectation_families import run
from test_boolean_fixture_provenance import BEFORE as BOOL_BEFORE, AFTER as BOOL_AFTER, PRODUCTION as BOOL_PROD
from test_callable_fixture_expectations import BEFORE as CALL_BEFORE, AFTER as CALL_AFTER, PRODUCTION as CALL_PROD
from test_callable_fixture_subjects import BEFORE as SUBJECT_BEFORE, AFTER as SUBJECT_AFTER, PRODUCTION as SUBJECT_PROD
from test_tuple_fixture_expectations import BEFORE as TUPLE_BEFORE, AFTER as TUPLE_AFTER, PRODUCTION as TUPLE_PROD


@pytest.mark.parametrize('before,after,production,fixture', [
    (BOOL_BEFORE, BOOL_AFTER, BOOL_PROD, 'expected_value'),
    (BOOL_BEFORE, BOOL_AFTER.replace('not 4 % 2 == 0', 'False'), BOOL_PROD, 'expected_value'),
    (CALL_BEFORE, CALL_AFTER, CALL_PROD, 'expected_adder'),
    (SUBJECT_BEFORE, SUBJECT_AFTER, SUBJECT_PROD, 'modified_make_adder'),
    (TUPLE_BEFORE, TUPLE_AFTER, TUPLE_PROD, 'expected_success_codes'),
])
@pytest.mark.parametrize('decorator', ['@pytest.fixture', '@pytest.fixture()'])
def test_reserved_fixture_definition_cannot_establish_answer_or_subject_provenance(before, after, production, fixture, decorator):
    assert f'def {fixture}(' in after
    after = after.replace(fixture, 'request').replace('@pytest.fixture', decorator)
    result = run(before, after, production)
    assert not [event for file in result[0].files for event in file.expected_provenance_events]
    assert not result[0].globals.subject_installations


def test_unused_invalid_fixture_cannot_authorize_a_computed_expected_fixture():
    after = BOOL_AFTER + '\n@pytest.fixture\ndef request():\n    return True\n'
    result = run(BOOL_BEFORE, after, BOOL_PROD)
    assert not [event for file in result[0].files for event in file.expected_provenance_events]


def test_reserved_fixture_withholds_full_call_graph_authority():
    data = b'import pytest\n@pytest.fixture\ndef request():\n    return True\ndef test_value(request):\n    assert request\n'
    assert not safe_call_graph(('tests/test_case.py',), {'tests/test_case.py': data}.get, scalar_fixtures=True)
