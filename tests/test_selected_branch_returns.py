"""A return in a proved selected branch also terminates the enclosing block."""
import textwrap

import pytest

from checkwash.frontends.python.frontend import parse_python
from test_issue_expectation_families import run


BEFORE = 'from app.prod import label\ndef test_value():\n    assert label(2) == 4\n'
PROD = 'def label(value):\n    return value + value\n'


def after(prefix):
    return 'from app.prod import label\ndef test_value():\n' + textwrap.indent(prefix, '    ') + '\n    assert label(2) == 4\n'


@pytest.mark.parametrize('prefix', [
    'if True:\n    return',
    'if 2 > 1:\n    return None',
    'if False:\n    pass\nelse:\n    return',
    'if True:\n    if True:\n        return',
    'if False:\n    pass\nelse:\n    if False:\n        pass\n    else:\n        return',
    'if True:\n    raise RuntimeError',
    'while False:\n    pass\nelse:\n    return',
    'for value in []:\n    pass\nelse:\n    return',
    'for value in ():\n    pass\nelse:\n    if True:\n        return',
    'enabled = True\nif enabled:\n    return',
])
def test_selected_branch_termination_removes_later_oracle(prefix):
    source = after(prefix)
    parsed = parse_python(source.encode(), collect_tests=True)
    assert not parsed.units[0].side.assertions
    _, findings, verdict = run(BEFORE, source, PROD)
    assert verdict == 'block'
    assert any(f.rule == 'ASSERT_REMOVED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('prefix', [
    'if False:\n    return',
    'if True:\n    pass\nelse:\n    return',
    'if unknown:\n    return',
    'while unknown:\n    return',
    'for value in unknown:\n    return',
    'try:\n    if True:\n        raise ValueError\nexcept ValueError:\n    pass',
    'try:\n    callback()\nexcept ValueError:\n    return',
    'if True:\n    try:\n        raise ValueError\n    except ValueError:\n        pass',
    'if True:\n    def helper():\n        return',
])
def test_unselected_or_unproved_termination_keeps_later_oracle(prefix):
    source = after(prefix)
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units[0].side.assertions) == 1


def test_assertion_in_return_expression_stays_on_the_executed_path():
    source = after('if True:\n    return label(2)')
    parsed = parse_python(source.encode(), collect_tests=True)
    assert 'label' in parsed.units[0].side.calls
    assert not parsed.units[0].side.assertions
