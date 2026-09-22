"""Default test regrouping requires framework authority without pytest imports."""
import pytest

from test_issue_expectation_families import run
from test_sequential_captured_oracles import BEFORE as SPLIT, AFTER as MERGED, PROD, projected


BEFORE = '''from app.prod import subject
def test_value():
    assert subject(1) == 1
    assert subject(2) == 2
'''
AFTER = '''from app.prod import subject
def test_value():
    assert subject(1) == 1
def test_tail():
    assert subject(2) == 2
'''
RUNNER = b'import runpy\nnamespace = runpy.run_path("tests/test_case.py")\nnamespace["test_value"]()\n'


@pytest.mark.parametrize('path', ['pytest.py', 'pytest/__init__.py', 'src/pytest.py',
                                'src/pytest/__init__.py', 'tests/pytest.py', 'tests/pytest/__init__.py'])
@pytest.mark.parametrize('before,after,production', [
    (BEFORE, AFTER, 'def subject(value):\n    return value\n'),
    (MERGED, SPLIT, PROD),
])
def test_native_assertions_and_complete_captures_cannot_assume_a_shadowed_collector(path, before, after, production):
    ir, _, _ = run(before, after, production, context={path: b''})
    assert not projected(ir)


@pytest.mark.parametrize('production', ['def subject(value):\n    return value\n', 'def subject(value):\n    return 1\n'])
def test_unchanged_local_runner_has_authority_over_which_native_tests_execute(production):
    ir, _, _ = run(BEFORE, AFTER, production, context={'pytest.py': RUNNER})
    assert not projected(ir)


@pytest.mark.parametrize('production', ['def subject(value):\n    return value\n', 'def subject(value):\n    return 1\n'])
def test_standard_framework_still_retains_both_passing_and_failing_oracles(production):
    ir, findings, verdict = run(BEFORE, AFTER, production)
    assert projected(ir) and verdict == 'pass' and not findings


def test_unrelated_inert_module_is_not_a_framework_shadow():
    ir, findings, verdict = run(BEFORE, AFTER, 'def subject(value):\n    return value\n',
                                context={'src/helpers.py': b'"""Unrelated helper package."""\n'})
    assert projected(ir) and verdict == 'pass' and not findings
