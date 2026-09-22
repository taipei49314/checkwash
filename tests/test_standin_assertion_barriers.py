"""Known failed assertions cannot lend execution proof to later stand-ins."""
import pytest

from test_patch_mock_consumers import PREFIX, result


PATCH = "with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement(6) == 8"


@pytest.mark.parametrize('barrier', [
    'assert False',
    'assert 1 == 2',
    'if True:\n    assert False',
    'if False:\n    pass\nelse:\n    assert False',
    'def stop():\n    assert False\nstop()',
    'def stop():\n    if True:\n        assert False\nstop()',
])
def test_known_assertion_failure_propagates_out_of_branches_and_helpers(barrier):
    assert not result(barrier + '\n' + PATCH)[0].globals.subject_installations


@pytest.mark.parametrize('barrier', ['assert True', 'if False:\n    assert False',
                                   'def stop():\n    assert False'])
def test_successful_or_unexecuted_assertion_does_not_abort_the_trace(barrier):
    assert result(barrier + '\n' + PATCH)[0].globals.subject_installations


def test_fixture_assertion_failure_prevents_later_test_consumption():
    prefix = PREFIX + '''import pytest
@pytest.fixture(autouse=True)
def setup():
    assert False
'''
    assert not result(PATCH, prefix=prefix)[0].globals.subject_installations


def test_prior_consumption_is_not_erased_by_a_later_failure():
    assert result(PATCH + '\nassert False')[0].globals.subject_installations


def test_failed_helper_cannot_allow_later_call_arguments_to_run():
    prefix = PREFIX + 'def stop():\n    assert False\n'
    assert not result('stop()\n' + PATCH, prefix=prefix)[0].globals.subject_installations
