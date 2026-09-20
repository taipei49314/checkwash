"""A consumed stub's call record can replace the production oracle (066/085)."""
import pytest

from test_standin_installations_main import hits, judge


PREFIX = 'from unittest.mock import patch\nfrom app.billing import total\n'
BEFORE = PREFIX + 'def test_total():\n    assert total(6) == 8\n'
AFTER = PREFIX + """def test_total():
    with patch('app.billing.total', return_value=8) as replacement:
        replacement(6)
        assert replacement.call_args == ((6,), {})
"""


def run(source, extra=None, before=BEFORE):
    return judge({'tests/test_total.py': before.encode()}, {'tests/test_total.py': source.encode()}, extra)


@pytest.mark.parametrize('target', ["patch('app.billing.total'", "patch.object(total, '__call__'"])
@pytest.mark.parametrize('assertion', ['assert replacement.call_args == ((6,), {})', 'replacement.assert_called_once_with(6)'])
def test_adjacent_literal_call_and_its_record_prove_mock_consumption(target, assertion):
    source = AFTER.replace("patch('app.billing.total'", target).replace('assert replacement.call_args == ((6,), {})', assertion)
    result = run(source)
    assert len(result[0].globals.subject_installations) == 1
    assert any(finding.severity == 'high' for finding in hits(result))


@pytest.mark.parametrize('source', [
    AFTER.replace('        replacement(6)\n', ''),
    AFTER.replace('        replacement(6)\n', '        total(6)\n'),
    AFTER.replace('replacement(6)', 'replacement(unknown)'),
    AFTER.replace('replacement(6)', 'replacement([][0])'),
    AFTER.replace('        replacement(6)', '        assert False\n        replacement(6)'),
    AFTER.replace('        replacement(6)', '        if enabled:\n            replacement(6)'),
    AFTER.replace('        replacement(6)', '        replacement = total\n        replacement(6)'),
    AFTER.replace('        assert replacement.call_args', '        replacement.reset_mock()\n        assert replacement.call_args'),
    AFTER.replace('        assert replacement.call_args', '        mutate()\n        assert replacement.call_args'),
    AFTER.replace('replacement.call_args', 'other.call_args'),
    AFTER.replace('== ((6,), {})', '== expected'),
    AFTER.replace('== ((6,), {})', '== ((6,), {}), mutate()'),
    AFTER.replace('assert replacement.call_args == ((6,), {})', 'replacement.assert_called_once_with(unknown)'),
    AFTER.replace('    with patch', '    assert False\n    with patch'),
    AFTER.replace('    with patch', '    mutate()\n    with patch'),
    AFTER.replace('def test_total():', 'def test_total(fixture):'),
    AFTER + '\ndef test_mutator():\n    mutate()\n',
    AFTER.replace('return_value=8', 'wraps=total'),
    AFTER.replace('return_value=8', 'side_effect=total'),
    AFTER.replace('return_value=8', 'side_effect=[]'),
])
def test_no_call_barriers_rebinding_and_unknown_record_reads_have_no_new_proof(source):
    assert not run(source)[0].globals.subject_installations


@pytest.mark.parametrize('extra', [
    {'tests/conftest.py': b'def pytest_runtest_setup(item):\n    mutate(item)\n'},
    {'tests/unittest.py': b'# custom patch provider\n'},
    {'src/unittest.py': b'# custom patch provider\n'},
])
def test_unknown_startup_and_patch_authority_withhold_record_proof(extra):
    assert not run(AFTER, extra)[0].globals.subject_installations


def test_record_consumer_alias_rename_does_not_create_new_installation():
    changed = AFTER.replace('import patch', 'import patch as standin').replace('with patch(', 'with standin(').replace('replacement', 'substitute')
    assert not run(changed, before=AFTER)[0].globals.subject_installations
