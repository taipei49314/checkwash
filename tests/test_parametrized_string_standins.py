"""Literal string methods cannot replace the imported production subject."""
import pytest

from checkwash import engine
from test_issue_expectation_families import run

PRODUCTION = 'def is_prefix(s, prefix):\n    return s.endswith(prefix)\n'
BEFORE = '''from app.prod import is_prefix
def test_prefix():
    assert is_prefix("foobar", "foo") is True
def test_not_prefix():
    assert is_prefix("foobar", "bar") is False
'''
AFTER = '''import pytest
from app.prod import is_prefix
@pytest.mark.parametrize('s, prefix, expected', [("foobar", "foo", True), ("foobar", "bar", False), ("", "", True)])
def test_is_prefix(s, prefix, expected):
    assert s.startswith(prefix) == expected
'''


def evidence(result):
    return result[0].globals.subject_installations


@pytest.mark.parametrize('after', [AFTER,
    AFTER.replace('s, prefix, expected', 's, prefix, answer').replace('== expected', '== answer'),
    AFTER.replace('test_is_prefix', 'test_combined'),
    AFTER.replace(', ("", "", True)', ''),
    AFTER.replace(', ("", "", True)', ', ("", "", True), ("abc", "ab", True)'),
])
@pytest.mark.parametrize('production', [PRODUCTION, PRODUCTION.replace('endswith', 'startswith')])
def test_exact_ordered_string_rows_add_existing_subject_replacement_evidence(after,production):
    result = run(BEFORE, after, production)
    assert result[2] == 'block' and len(evidence(result)) == 1
    path, unit, target, text, span = evidence(result)[0]
    assert path == 'tests/test_case.py' and target == 'app.prod.is_prefix'
    assert after[slice(*span)] == text
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' and f.severity == 'high' for f in result[1])


def test_evidence_leaves_oracle_operators_alignment_and_assertion_ir_unchanged(monkeypatch):
    current = run(BEFORE, AFTER, PRODUCTION)
    monkeypatch.setattr(engine, 'parametrized_string_standin_events', lambda *args, **kwargs: [])
    previous = run(BEFORE, AFTER, PRODUCTION)
    assert current[0].files == previous[0].files


@pytest.mark.parametrize('production', [PRODUCTION, PRODUCTION.replace('endswith', 'startswith')])
def test_parametrized_consumer_that_still_calls_production_is_not_a_standin(production):
    after = AFTER.replace('s.startswith(prefix) == expected', 'is_prefix(s, prefix) is expected')
    result = run(BEFORE, after, production)
    assert not evidence(result) and result[2] == 'pass' and not result[1]


@pytest.mark.parametrize('old,new', [
    ('("foobar", "foo", True)', '("foobar", "foo", False)'),
    ('("foobar", "foo", True)', '("other", "foo", True)'),
    ('("foobar", "foo", True)', '("foobar", "other", True)'),
    ('("foobar", "foo", True)', '("foobar", "foo", 1)'),
    ('("foobar", "foo", True)', '("foobar", ("foo",), True)'),
    ('("foobar", "foo", True)', '(custom(), "foo", True)'),
    ('("foobar", "foo", True), ("foobar", "bar", False)', '("foobar", "bar", False), ("foobar", "foo", True)'),
    ('("foobar", "bar", False), ', ''),
    ('("", "", True)', '("", "", object())'),
    ('s, prefix, expected', 's, prefix, s'),
    ('s, prefix, expected', 's, prefix, is_prefix'),
    ('s, prefix, expected', 's, prefix, __debug__'),
    ('s.startswith(prefix)', 'prefix.startswith(s)'),
    ('s.startswith(prefix)', 's.endswith(prefix)'),
    ('s.startswith(prefix)', 's.startswith(prefix, 0)'),
    ('s.startswith(prefix)', 's.startswith(prefix=prefix)'),
    ('s.startswith(prefix)', 's.startswith(prefix=prefix, prefix=prefix)'),
    ('s.startswith(prefix)', 'custom(s).startswith(prefix)'),
    ('== expected', 'is expected'),
    ('== expected', '== prefix'),
    ('== expected', '== expected, callback()'),
    ('    assert s.startswith', '    s = custom()\n    assert s.startswith'),
    ('    assert s.startswith', '    return\n    assert s.startswith'),
    ('def test_is_prefix', '@pytest.mark.skip\ndef test_is_prefix'),
    ('def test_is_prefix(s, prefix, expected):', 'def test_is_prefix(s, prefix, expected, request):'),
    ('import pytest', 'import pytest as framework'),
    ('import pytest', 'import pytest\nimport callback'),
    ('import is_prefix', 'import is_prefix as other'),
])
def test_input_answer_multiplicity_receiver_and_collection_boundaries_decline(old,new):
    assert not evidence(run(BEFORE, AFTER.replace(old,new), PRODUCTION))


@pytest.mark.parametrize('before', [
    BEFORE.replace(' is True', ' == True'),
    BEFORE.replace('is_prefix("foobar", "foo")', 'is_prefix(s="foobar", prefix="foo")'),
    BEFORE.replace('def test_prefix():', '@decorate\ndef test_prefix():'),
    BEFORE.replace('def test_prefix():', 'def test_prefix(fixture):'),
    BEFORE.replace('is True', 'is True, callback()'),
    BEFORE + '\ndef test_duplicate():\n    assert is_prefix("foobar", "foo") is True\n',
])
def test_prior_complete_identity_oracle_prefix_is_required(before):
    assert not evidence(run(before, AFTER, PRODUCTION))


@pytest.mark.parametrize('production', [
    'import callback\n' + PRODUCTION,
    PRODUCTION + 'is_prefix = custom\n',
    'def is_prefix(s, prefix):\n    return callback(s, prefix)\n',
    'class Custom:\n    pass\ndef is_prefix(s, prefix):\n    return Custom()\n',
    'def is_prefix(s, prefix):\n    global is_prefix\n    is_prefix = custom\n    return True\n',
    'def is_prefix(s, prefix):\n    return s.endswith(prefix)\ndef mutate():\n    callback()\n',
    'def is_prefix(s, prefix):\n    return s.endswith(prefix=prefix)\n',
    'def is_prefix(s, prefix):\n    return s.endswith(prefix, 0)\n',
    'def is_prefix(s, prefix=callback()):\n    return s.endswith(prefix)\n',
    'def is_prefix(__debug__, prefix):\n    return __debug__.endswith(prefix)\n',
])
def test_complete_source_is_primitive_and_cannot_rebind_the_subject_or_framework(production):
    assert not evidence(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('context', [
    {'pytest.py':b''}, {'tests/pytest/__init__.py':b''}, {'app/__init__.py':b''},
    {'src/app/__init__.py':b'import pytest\npytest.mark.parametrize = custom\n'},
    {'src/sitecustomize.py':b'import builtins\nbuiltins.__import__ = custom\n'},
    {'tests/conftest.py':b'import pytest\n@pytest.fixture(autouse=True)\ndef change():\n    mutate()\n'},
    {'pytest.ini':b'[pytest]\ntestpaths=tests/elsewhere\n'},
    {'tests/test_sibling.py':b'def test_mutator():\n    mutate()\n'},
])
def test_complete_startup_framework_and_active_collection_authority_is_required(context):
    assert not evidence(run(BEFORE, AFTER, PRODUCTION, context=context))
