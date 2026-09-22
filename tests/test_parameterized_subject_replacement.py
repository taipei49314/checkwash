"""Literal helper parameters must not hide builtin substitution (escape044)."""
import pytest

from test_issue132_subject_replacements import PREFIX, judge


BEFORE = PREFIX + '''def test_total():
    assert total(5) == 5
    assert total(-3) == 3
    assert total(0) == 0
'''
AFTER = PREFIX + '''import pytest
def check_value(value, expected):
    assert abs(value) == expected
def test_total():
    check_value(5, 5)
    check_value(-3, 3)
    check_value(0, 0)
'''


@pytest.mark.parametrize('after', [
    AFTER,
    AFTER.replace('import pytest', 'import builtins').replace('abs(value)', 'builtins.abs(value)'),
    AFTER.replace('import pytest', 'from builtins import abs as magnitude').replace('abs(value)', 'magnitude(value)'),
    AFTER.replace('check_value(value, expected)', 'check_value(expected, value)').replace(
        'check_value(-3, 3)', 'check_value(3, -3)'),
])
def test_literal_parameter_helper_records_first_consumed_builtin_replacement(after):
    hits = [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']
    assert len(hits) == 1 and hits[0].severity == 'high'
    assert hits[0].after.text == 'check_value(5, 5)'


@pytest.mark.parametrize('after', [
    AFTER.replace('abs(value)', 'total(value)'),
    AFTER.replace('abs(value)', 'other(value)'),
    AFTER.replace('import pytest', 'abs = total'),
    AFTER.replace('check_value(value, expected)', 'check_value(abs, expected)').replace('abs(value)', 'abs(abs)'),
    AFTER.replace('    check_value(5, 5)', '    if enabled:\n        check_value(5, 5)'),
    AFTER.replace('    check_value(5, 5)', '    assert False\n    check_value(5, 5)'),
    AFTER.replace('def test_total():', 'def test_total(check_value):'),
    AFTER.replace('def check_value', '@decorate\ndef check_value'),
    AFTER.replace('check_value(value, expected)', 'check_value(value, expected=3)'),
    AFTER.replace('check_value(value, expected)', 'check_value(value: Provider, expected)'),
    AFTER.replace('    assert abs(value)', '    mutate()\n    assert abs(value)'),
    AFTER + '\ncheck_value = other\n',
    AFTER + '\ndef test_callback():\n    mutate()\n',
    AFTER + '\nasync def test_callback():\n    mutate()\n',
    AFTER.replace('== expected', '== expected, mutate()'),
    AFTER.replace('abs(value)', '0 == 1 == abs(value)'),
    AFTER.replace('check_value(5, 5)', 'check_value(make_value(), 5)'),
    AFTER.replace('check_value(5, 5)', 'check_value(*[5, 5])'),
    AFTER.replace('check_value(5, 5)', 'check_value(value=5, expected=5)'),
])
def test_forwarding_unknown_dispatch_and_barriers_do_not_borrow_helper_proof(after):
    assert not [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize('after', [
    AFTER.replace('check_value(-3, 3)', 'check_value(-3, 4)'),
    AFTER.replace('check_value(-3, 3)', 'check_value(-4, 3)'),
    AFTER.replace('    check_value(-3, 3)\n', ''),
    AFTER + '    check_value(10, 10)\n',
    AFTER.replace('check_value(5, 5)\n    check_value(-3, 3)', 'check_value(-3, 3)\n    check_value(5, 5)'),
])
def test_changed_input_answer_count_or_order_withholds_exact_helper_mapping(after):
    assert not [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


def test_unused_helper_does_not_replace_the_original_call():
    after = AFTER[:AFTER.index('def test_total')] + BEFORE[BEFORE.index('def test_total'):]
    assert not [finding for finding in judge(BEFORE, after) if finding.rule == 'TEST_PATCHES_SUBJECT']


def test_literal_helper_masks_bug_without_exercising_production():
    calls = []
    def production(value):
        calls.append(value)
        return value
    old, new = {'total': production}, {'total': production}
    exec(BEFORE.removeprefix(PREFIX), old)
    exec(AFTER.removeprefix(PREFIX), new)
    with pytest.raises(AssertionError):
        old['test_total']()
    new['test_total']()
    assert calls == [5, -3]
    assert any(finding.rule == 'TEST_PATCHES_SUBJECT' for finding in judge(BEFORE, AFTER))


@pytest.mark.parametrize('extra', [
    {'app/billing.py': b'import builtins\ndef total(n):\n    return n\nbuiltins.abs=total\n'},
    {'app/__init__.py': b'import builtins\nfrom .billing import total\nbuiltins.abs=total\n'},
    {'tests/conftest.py': b'def pytest_configure():\n    import builtins\n    from app.billing import total\n    builtins.abs=total\n'},
    {'tests/test_aaa.py': b'import builtins\nfrom app.billing import total\nbuiltins.abs=total\n'},
    {'tests/__init__.py': b'import builtins\nfrom app.billing import total\nbuiltins.abs=total\n'},
    {'pytest.ini': b'[pytest]\naddopts=-p mutator\n'},
    {'pytest.py': b'import builtins\nfrom app.billing import total\nbuiltins.abs=total\n'},
])
def test_imported_source_and_startup_cannot_rebind_the_builtin(extra):
    assert not [f for f in judge(BEFORE, AFTER, extra) if f.rule == 'TEST_PATCHES_SUBJECT']


def test_extra_import_cannot_borrow_production_source_authority():
    after = AFTER.replace('import pytest', 'import pytest\nimport mutator')
    assert not [f for f in judge(BEFORE, after) if f.rule == 'TEST_PATCHES_SUBJECT']


def test_rebound_builtin_helper_still_calls_production(monkeypatch):
    import builtins
    calls = []
    def total(value):
        calls.append(value)
        return value if value >= 0 else -value
    monkeypatch.setattr(builtins, 'abs', total)
    for source in (BEFORE, AFTER):
        namespace = {'total': total}
        exec(source.removeprefix(PREFIX), namespace)
        namespace['test_total']()
    assert calls == [5, -3, 0, 5, -3, 0]
    production = b'import builtins\ndef total(n):\n    return n if n >= 0 else -n\nbuiltins.abs=total\n'
    assert not [f for f in judge(BEFORE, AFTER, {'app/billing.py': production}) if f.rule == 'TEST_PATCHES_SUBJECT']
