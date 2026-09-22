"""A local string clone must not replace the asserted production call (C1)."""
import pytest

from test_issue132_subject_replacements import PREFIX, judge


BEFORE = PREFIX + 'def test_total():\n    assert total("  Hello   WORLD  ") == "hello world"\n'
HELPER = 'def local_clone(value):\n    return " ".join(value.split()).lower()\n'
AFTER = PREFIX + HELPER + BEFORE.removeprefix(PREFIX).replace('assert total(', 'assert local_clone(')


@pytest.mark.parametrize('expression', [
    '" ".join(value.split()).lower()', '" ".join(value.lower().split())',
    'value.strip().lower()', 'value.lstrip().rstrip().casefold()', 'value.upper().lower()',
])
def test_concrete_string_clone_subject_is_detected(expression):
    after = AFTER.replace('" ".join(value.split()).lower()', expression)
    hits = [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']
    assert len(hits) == 1 and hits[0].severity == 'high'


@pytest.mark.parametrize('expression', [
    'total(value)', 'provider(value).lower()', 'value.unknown()',
    '" ".join(provider(value))', 'other.lower()', 'value.split(separator)',
    'value.split("")', '" ".join(value)', 'value.format()', 'str(value).lower()',
])
def test_unknown_receivers_callbacks_and_unproved_dispatch_do_not_install(expression):
    after = AFTER.replace('" ".join(value.split()).lower()', expression)
    assert not [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('value', ['item', 'StringLike()', 'make_value()', '["a"]', 'b"a"'])
def test_nonliteral_argument_cannot_claim_primitive_method_dispatch(value):
    before, after = [source.replace('"  Hello   WORLD  "', value) for source in (BEFORE, AFTER)]
    assert not [finding for finding in judge(before, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('edit', [
    lambda source: source.replace('def local_clone(value):', '@decorate\ndef local_clone(value):'),
    lambda source: source.replace('def local_clone(value):', 'def local_clone(value=external()):'),
    lambda source: source.replace('def local_clone(value):', 'def local_clone(value: external()):'),
    lambda source: source.replace('def local_clone(value):', 'async def local_clone(value):'),
    lambda source: source.replace('def test_total():', 'def test_total(local_clone):'),
    lambda source: source.replace('def test_total():', '@decorate\ndef test_total():'),
    lambda source: source.replace('    assert local_clone(', '    mutate()\n    assert local_clone('),
    lambda source: source + '\nlocal_clone = total\n',
    lambda source: source + '\nlocal_clone.__code__ = total.__code__\n',
    lambda source: source + '\nglobals()["local_clone"] = total\n',
    lambda source: source + '\ndef setup_function():\n    mutate()\n',
    lambda source: source + '\ndef test_callback():\n    mutate()\n',
    lambda source: source + '\ndef test_callback():\n    assert mutate(local_clone)\n',
    lambda source: source.replace('== "hello world"', '== mutate()'),
    lambda source: source.replace('== "hello world"', '== "hello world", mutate()'),
])
def test_unknown_helper_identity_does_not_supply_string_clone_proof(edit):
    assert not [finding for finding in judge(BEFORE, edit(AFTER)) if finding.rule == 'TEST_PATCHES_SUBJECT']


def test_input_expected_edits_and_unused_clone_are_not_subject_replacement():
    for after in (AFTER.replace('"  Hello   WORLD  "', '"different"'),
                  AFTER.replace('== "hello world"', '== "different"'),
                  PREFIX + HELPER + BEFORE.removeprefix(PREFIX)):
        assert not [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


def test_literal_clone_masks_real_production_failure():
    observed = []
    def production(value):
        observed.append(value)
        return value.lower()
    old, new = {'total': production}, {'total': production}
    exec(BEFORE.removeprefix(PREFIX), old)
    exec(AFTER.removeprefix(PREFIX), new)
    with pytest.raises(AssertionError):
        old['test_total']()
    new['test_total']()
    assert observed == ['  Hello   WORLD  ']
    assert any(finding.rule == 'TEST_PATCHES_SUBJECT' for finding in judge(BEFORE, AFTER))
