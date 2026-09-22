"""A literal True class guard composes with the closed normalization proof."""
import pytest

from test_builtin_normalization_oracles import marked as _marked
from test_issue_expectation_families import run

PROD = 'def average(xs):\n    return sum(xs)\n'
BEFORE = '''from app.prod import average
class TestAverage:
    ENFORCE = True
    def test_average(self):
        if type(self).ENFORCE:
            assert average([2, 4]) == 3
'''
AFTER = BEFORE.replace('average([2, 4]) == 3', 'str(average([2, 4]))[:0] == str(3)[:0]')


def marked(ir):
    return [assertion for assertion in _marked(ir) if 'str(average(' in assertion.text]


@pytest.mark.parametrize('edit', [lambda s:s, lambda s:s.replace('ENFORCE', 'enabled'),
                                lambda s:'"説明"\n'+s, lambda s:s.replace('\n', '\r\n')])
def test_literal_true_class_guard_keeps_original_assertion_and_span(edit):
    new = edit(AFTER)
    ir, findings, verdict = run(edit(BEFORE), new, PROD)
    found = marked(ir)
    assert len(found) == 1 and found[0].trivial and found[0].strength == 10
    assert new.replace('\r\n','\n')[slice(*found[0].span)].strip() == found[0].text
    assert verdict == 'block' and any(f.rule == 'ASSERT_WEAKENED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [PROD, 'def average(xs):\n    return sum(xs) / len(xs)\n'])
def test_honest_exact_helper_under_same_guard_preserves_the_oracle(production):
    new = BEFORE.replace('assert average([2, 4]) == 3', 'check(average([2, 4]), 3)')
    new += '\ndef check(actual, expected):\n    assert actual == expected\n'
    ir, findings, verdict = run(BEFORE, new, production)
    assert not marked(ir)
    # The new pass adds no evidence; the existing helper expansion handles it.
    assert verdict == 'pass' and not findings


@pytest.mark.parametrize('old,new', [
    ('ENFORCE = True', 'ENFORCE = False'), ('ENFORCE = True', 'ENFORCE = 1'),
    ('ENFORCE = True', 'ENFORCE = bool(1)'), ('ENFORCE = True', 'ENFORCE: bool = True'),
    ('ENFORCE = True', 'ENFORCE = other = True'), ('ENFORCE = True', 'ENFORCE = True\n    ENFORCE = False'),
    ('ENFORCE = True', '__test__ = False\n    ENFORCE = True'),
    ('class TestAverage:', 'class TestAverage(Base):'),
    ('class TestAverage:', 'class TestAverage(metaclass=Meta):'),
    ('class TestAverage:', '@decorate\nclass TestAverage:'),
    ('class TestAverage:', 'class Checks:'),
    ('def test_average(self):', '@property\n    def test_average(self):'),
    ('def test_average(self):', 'def test_average(self, type):'),
    ('def test_average(self):', 'def test_average(self) -> callback():'),
    ('def test_average(self):', 'def __init__(self):'),
    ('if type(self).ENFORCE:', 'if self.ENFORCE:'),
    ('if type(self).ENFORCE:', 'if TestAverage.ENFORCE:'),
    ('if type(self).ENFORCE:', 'if custom(self).ENFORCE:'),
    ('if type(self).ENFORCE:', 'if type(object=self).ENFORCE:'),
    ('if type(self).ENFORCE:', 'if type(self).other:'),
    ('        if type(self).ENFORCE:', '        self.ENFORCE = False\n        if type(self).ENFORCE:'),
    ('        if type(self).ENFORCE:', '        mutate()\n        if type(self).ENFORCE:'),
    ('            assert', '            return\n            assert'),
])
def test_unknown_class_guard_binding_and_execution_barriers_withhold(old,new):
    assert not marked(run(BEFORE.replace(old,new), AFTER.replace(old,new), PROD)[0])


@pytest.mark.parametrize('suffix', [
    '\nclass TestChild(TestAverage):\n    ENFORCE = False\n',
    '\nclass TestOther:\n    def test_ok(self):\n        assert True\n',
    '\nTestAverage.ENFORCE = False\n',
    '\ndef setUpModule():\n    TestAverage.ENFORCE = False\n',
])
def test_inheritance_siblings_and_later_rebindings_prevent_isolated_class_proof(suffix):
    assert not marked(run(BEFORE+suffix, AFTER+suffix, PROD)[0])


@pytest.mark.parametrize('context', [
    {'conftest.py': b'def pytest_collection_modifyitems(items):\n    items.clear()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.type = custom\n'},
    {'tests/test_other.py': b'def test_other():\n    from tests.test_case import TestAverage\n    TestAverage.ENFORCE = False\n'},
    {'pytest.ini': b'[pytest]\npython_classes=Checks\n'},
    {'pytest.ini': b'[pytest]\ntestpaths=tests/other\n'},
])
def test_closed_class_proof_requires_unchanged_execution_authority(context):
    assert not marked(run(BEFORE, AFTER, PROD, context=context)[0])
