"""A helper call behind a proved return cannot lend inherited assertions."""
import textwrap

import pytest

from checkwash.frontends.python.frontend import parse_python
from test_issue_expectation_families import run


PROD = 'def label(value):\n    return value + value\n'
HELPER = 'def check_value():\n    assert label(2) == 4\n'


@pytest.mark.parametrize('definition,body', [
    (HELPER, 'check_value()'),
    ('', 'def check_value():\n    assert label(2) == 4\ncheck_value()'),
    ('class Probe:\n    def __init__(self):\n        assert label(2) == 4\n', 'Probe()'),
])
@pytest.mark.parametrize('barrier', ['return', 'return None', 'if True:\n    return',
                                   'if False:\n    pass\nelse:\n    return'])
def test_unreachable_module_nested_and_constructor_entries_lose_their_oracle(definition, body, barrier):
    prefix = 'from app.prod import label\n' + definition + 'def test_value():\n'
    before = prefix + textwrap.indent(body, '    ') + '\n'
    after = prefix + textwrap.indent(barrier + '\n' + body, '    ') + '\n'
    assert len(parse_python(before.encode(), collect_tests=True).units[0].side.assertions) == 1
    assert not parse_python(after.encode(), collect_tests=True).units[0].side.assertions
    _, findings, verdict = run(before, after, PROD)
    assert verdict == 'block'
    assert any(f.rule == 'ASSERT_REMOVED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('body', [
    'return check_value()',
    'if True:\n    return check_value()',
    'if False:\n    return\ncheck_value()',
    'if unknown:\n    return\ncheck_value()',
    'try:\n    raise ValueError\nexcept ValueError:\n    pass\ncheck_value()',
])
def test_reached_or_unproved_helper_entries_keep_inherited_oracles(body):
    source = 'from app.prod import label\n' + HELPER + 'def test_value():\n' + textwrap.indent(body, '    ') + '\n'
    assertions = parse_python(source.encode(), collect_tests=True).units[0].side.assertions
    assert len(assertions) == 1 and assertions[0].inherited


def test_only_dead_entry_copy_is_removed_when_another_call_still_executes():
    source = ('from app.prod import label\n' + HELPER + 'def test_value():\n'
              '    check_value()\n    return\n    check_value()\n')
    assert len(parse_python(source.encode(), collect_tests=True).units[0].side.assertions) == 1
