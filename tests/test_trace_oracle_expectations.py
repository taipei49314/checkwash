"""The final empty mismatch list consumes its concrete comparison answer."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def reverse(value):\n    return value\n'
BEFORE = '''from app.prod import reverse
def test_reverse():
    mismatches = []
    got = reverse("abc")
    if got != "cba":
        mismatches.append((got, "cba"))
    assert not mismatches
'''
AFTER = BEFORE.replace('    mismatches = []', '''    def reverse_compare(got, expected):
        return got == expected[::-1]
    mismatches = []''').replace('if got != "cba":', 'if not reverse_compare(got, "cba"):')


def provenance(result):
    return [event for file in result[0].files for event in file.expected_provenance_events]


@pytest.mark.parametrize('before,after', [
    (BEFORE, AFTER),
    (BEFORE.replace('got != "cba"', 'not (got == "cba")'), AFTER),
    (BEFORE, AFTER.replace('expected[::-1]', 'expected[2] + expected[1] + expected[0]')),
    (BEFORE, AFTER.replace('expected[::-1]', '"abc"')),
    (BEFORE.replace('reverse', 'reverse_alias'), AFTER.replace('reverse', 'reverse_alias')),
    (BEFORE, AFTER.replace('mismatches', 'errors').replace('got', 'result')),
    (BEFORE.replace('\n', '\r\n'), AFTER.replace('\n', '\r\n')),
])
def test_changed_trace_comparison_answer_keeps_original_assertion(before, after):
    production = PRODUCTION.replace('reverse', 'reverse_alias') if 'reverse_alias' in before else PRODUCTION
    result = run(before, after, production)
    assert result[2] == 'block'
    findings = [finding for finding in result[1] if finding.rule == 'EXPECTATION_DEFINITION_CHANGED']
    assert len(findings) == 1
    events = provenance(result)
    assert [event[-3:] for event in events] == [('Eq', "'cba'", "'abc'")]
    for source, text, span in ((before, events[0][1], events[0][2]), (after, events[0][3], events[0][4])):
        assert source.replace('\r\n', '\n')[slice(*span)] == text
    unit = result[0].files[0].units[0]
    assert unit.before.assertions[0].text == 'assert not mismatches'
    assert unit.before.assertions[0].strength == unit.after.assertions[0].strength


def test_honest_comparison_helper_extraction_retains_answer_without_new_event():
    result = run(BEFORE, AFTER.replace('expected[::-1]', 'expected'), PRODUCTION)
    assert not provenance(result) and not result[1] and result[2] == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('reverse("abc")', 'reverse("abcd")'),
    AFTER.replace('reverse("abc")', 'other("abc")'),
    AFTER.replace('reverse("abc")', 'reverse(value="abc")'),
    AFTER.replace('reverse("abc")', 'reverse(custom)'),
    AFTER.replace('reverse("abc")', 'reverse("abc", "x")'),
    AFTER.replace('got = reverse("abc")', 'got = "abc"'),
    AFTER.replace('got = reverse("abc")', 'got = reverse("abc").strip()'),
    AFTER.replace('def test_reverse():', 'def test_reverse(reverse):'),
    AFTER.replace('def test_reverse():', 'def test_reverse(reverse=other):'),
    AFTER.replace('def test_reverse():', '@pytest.mark.skip\ndef test_reverse():'),
    AFTER.replace('test_reverse', 'test_renamed'),
])
def test_changed_or_unknown_subject_input_never_claims_same_trace(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('mismatches = []', 'mismatches = ["earlier"]'),
    AFTER.replace('mismatches = []', 'mismatches = factory()'),
    AFTER.replace('mismatches = []', 'mismatches = got = []'),
    AFTER.replace('mismatches = []', 'mismatches = reverse = []'),
    AFTER.replace('got = reverse("abc")', 'mismatches = reverse("abc")'),
    AFTER.replace('    got =', '    alias = mismatches\n    got ='),
    AFTER.replace('    got =', '    assert False\n    got ='),
    AFTER.replace('    got =', '    mutate()\n    got ='),
    AFTER.replace('        mismatches.append((got, "cba"))', '        pass'),
    AFTER.replace('append((got, "cba"))', 'extend((got, "cba"))'),
    AFTER.replace('append((got, "cba"))', 'append((got, message()))'),
    AFTER.replace('append((got, "cba"))', 'append((got, "abc"))'),
    AFTER.replace('append((got, "cba"))', 'append((other, "cba"))'),
    AFTER.replace('    assert not mismatches', '    else:\n        mismatches.append((got, "cba"))\n    assert not mismatches'),
    AFTER.replace('    assert not mismatches', '    mismatches.clear()\n    assert not mismatches'),
    AFTER.replace('assert not mismatches', 'assert mismatches'),
    AFTER.replace('assert not mismatches', 'assert not other'),
    AFTER.replace('assert not mismatches', 'assert not mismatches, message()'),
    AFTER.replace('if not reverse_compare', 'if reverse_compare'),
    AFTER.replace('if not reverse_compare(got, "cba")', 'if flag and not reverse_compare(got, "cba")'),
])
def test_trace_must_initialize_append_and_consume_the_same_local_list(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('expected[::-1]', 'got[::-1]'),
    AFTER.replace('expected[::-1]', 'external(expected)'),
    AFTER.replace('expected[::-1]', 'expected + suffix'),
    AFTER.replace('expected[::-1]', 'expected[99]'),
    AFTER.replace('expected[::-1]', 'expected[::0]'),
    AFTER.replace('expected[::-1]', '(mutate(), "abc")[1]'),
    AFTER.replace('got == expected[::-1]', 'got is expected[::-1]'),
    AFTER.replace('got == expected[::-1]', 'got != expected[::-1]'),
    AFTER.replace('got == expected[::-1]', 'True'),
    AFTER.replace('got, expected):', 'got, expected="cba"):'),
    AFTER.replace('got, expected):', 'got, got):'),
    AFTER.replace('def reverse_compare', '@decorate\n    def reverse_compare'),
    AFTER.replace('return got ==', 'mutate()\n        return got =='),
    AFTER.replace('reverse_compare', 'reverse'),
    AFTER.replace('reverse_compare', 'mismatches'),
    AFTER.replace('reverse_compare', 'got'),
    AFTER + '\ndef test_other():\n    mutate()\n',
    'import mutator\n' + AFTER,
    AFTER + '\nreverse = replacement\n',
])
def test_helper_and_module_binding_must_be_closed(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('production', [
    'def reverse(value):\n    return Custom(value)\n',
    'def reverse(value):\n    return external(value)\n',
    'def reverse(value):\n    mutate()\n    return value\n',
    'def reverse(value):\n    return [value]\n',
    'import mutator\n' + PRODUCTION,
    PRODUCTION + 'reverse.__code__ = other.__code__\n',
    'from tests.test_case import test_reverse\n' + PRODUCTION,
])
def test_complete_primitive_string_production_source_is_required(production):
    assert not provenance(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('context', [
    {'pytest.py': b''},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/__init__.py': b'import app.prod\napp.prod.reverse = lambda value: value\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
    {'tests/test_aaa.py': b'import app.prod\napp.prod.reverse = lambda value: value\n'},
    {'pytest.ini': b'[pytest]\naddopts=-p mutator\n'},
])
def test_executable_startup_and_custom_binding_authority_withhold_trace(context):
    assert not provenance(run(BEFORE, AFTER, PRODUCTION, context=context))
