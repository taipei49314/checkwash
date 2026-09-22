"""A repeated keyword is a compile error, not a concrete executed oracle."""
import pytest

from test_issue_expectation_families import run


@pytest.mark.parametrize('comparison', ['==', 'is'])
@pytest.mark.parametrize('second', ['200', '201'])
def test_duplicate_keyword_does_not_obtain_table_or_boolean_pair_credit(comparison, second):
    before = f'from app.prod import success\ndef test_value():\n    assert success(code=200, code={second}) == True\n'
    after = f'''import pytest
from app.prod import success
@pytest.mark.parametrize('expected', [True])
def test_value(expected):
    assert success(code=200, code={second}) {comparison} expected
'''
    for source in (before, after):
        with pytest.raises(SyntaxError, match='keyword argument repeated'):
            compile(source, '<test>', 'exec')
    ir, _, _ = run(before, after, 'def success(code):\n    return True\n')
    assert not any(u.qualname.startswith('test_concrete_') for f in ir.files for u in f.units)


def test_distinct_literal_keywords_still_preserve_a_complete_oracle():
    before = 'from app.prod import success\ndef test_value():\n    assert success(left=200, right=200) == True\n'
    after = '''import pytest
from app.prod import success
@pytest.mark.parametrize('expected', [True])
def test_value(expected):
    assert success(left=200, right=200) is expected
'''
    ir, findings, verdict = run(before, after, 'def success(left, right):\n    return left == right\n')
    assert any(u.qualname.startswith('test_concrete_') for f in ir.files for u in f.units)
    assert not findings and verdict == 'pass'
