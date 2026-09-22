"""A closed default-class consumer retains its aliased assertion catcher."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def average(xs):\n    return sum(xs)\n'
BEFORE = '''from app.prod import average
class TestAverage:
    ENFORCE = True
    def test_average(self):
        if type(self).ENFORCE:
            assert average([2, 4]) == 3
'''
AFTER = '''from app.prod import average
import pytest
_E = AssertionError
class TestAverage:
    ENFORCE = True
    def test_average(self):
        if type(self).ENFORCE:
            with pytest.raises(_E):
                assert average([2, 4]) == 3
'''


def contexts(before=BEFORE, after=AFTER, production=PRODUCTION, *, context=None):
    result = run(before, after, production, context=context)
    return result, [text for _, text in result[0].globals.broad_excepts_added if '(_E)' in text]


@pytest.mark.parametrize('exception', ['AssertionError', 'Exception', 'BaseException'])
@pytest.mark.parametrize('framework', ['pytest', 'testing'])
def test_builtin_exception_alias_in_closed_default_class_blocks(exception, framework):
    after = AFTER.replace('AssertionError', exception)
    if framework != 'pytest':
        after = after.replace('import pytest', 'import pytest as testing').replace('with pytest.', 'with testing.')
    result, evidence = contexts(after=after)
    assert evidence == [framework + '.raises(_E)'] and result[2] == 'block'
    assert any(f.rule == 'BROAD_EXCEPT_ADDED' and f.severity == 'high' for f in result[1])
    unit = result[0].files[0].units[0]
    original = [item for item in unit.after.assertions if item.form == 'compare_eq']
    assert len(unit.before.assertions) == len(original) == 1
    assert unit.before.assertions[0].text == original[0].text


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('class TestAverage:', 'class TestAverage(Base):'),
    lambda s: s.replace('class TestAverage:', 'class TestAverage(metaclass=Meta):'),
    lambda s: s.replace('class TestAverage:', '@decorate\nclass TestAverage:'),
    lambda s: s.replace('ENFORCE = True', 'ENFORCE = False'),
    lambda s: s.replace('ENFORCE = True', 'ENFORCE = 1'),
    lambda s: s.replace('ENFORCE = True', 'ENFORCE = callback()'),
    lambda s: s.replace('ENFORCE = True', 'ENFORCE: bool = True'),
    lambda s: s.replace('ENFORCE = True', '__test__ = False\n    ENFORCE = True'),
    lambda s: s.replace('ENFORCE = True', '__slots__ = 3\n    ENFORCE = True'),
    lambda s: s.replace('    def test_average', '    def __getattribute__(self, key):\n        return False\n    def test_average'),
    lambda s: s.replace('    def test_average', '    def setup_method(self):\n        mutate()\n    def test_average'),
    lambda s: s.replace('    def test_average', '    @pytest.mark.skip\n    def test_average'),
    lambda s: s.replace('    def test_average', '    @staticmethod\n    def test_average'),
    lambda s: s.replace('    def test_average', '    async def test_average'),
    lambda s: s.replace('test_average(self)', 'test_average(self, request)'),
    lambda s: s.replace('test_average(self)', 'test_average(self=callback())'),
    lambda s: s.replace('test_average(self):', 'test_average(self) -> callback():'),
    lambda s: s.replace('if type(self).ENFORCE:', 'if self.ENFORCE:'),
    lambda s: s.replace('if type(self).ENFORCE:', 'if type(self).OTHER:'),
    lambda s: s.replace('if type(self).ENFORCE:', 'if type(other).ENFORCE:'),
    lambda s: s.replace('if type(self).ENFORCE:', 'if callback(self).ENFORCE:'),
    lambda s: s.replace('        if type', '        return\n        if type'),
    lambda s: s.replace('        if type', '        assert False\n        if type'),
    lambda s: s.replace('        if type', '        _E = ValueError\n        if type'),
    lambda s: s.replace('        if type', '        type = callback\n        if type'),
    lambda s: s.replace('_E = AssertionError', '_E = ValueError'),
    lambda s: s.replace('_E = AssertionError', '_E = Error'),
    lambda s: s.replace('_E = AssertionError', '_E = AssertionError\n_E = ValueError'),
    lambda s: s.replace('_E = AssertionError', '_E = AssertionError\ndel _E'),
    lambda s: s.replace('_E = AssertionError', '_E = factory()'),
    lambda s: s.replace('_E = AssertionError', '_E: type = AssertionError'),
    lambda s: s.replace('_E = AssertionError', '_E = other = AssertionError'),
    lambda s: s.replace('pytest.raises(_E)', 'pytest.raises(_E, match="boom")'),
    lambda s: s.replace('pytest.raises(_E)', 'pytest.raises((_E,))'),
    lambda s: s.replace('pytest.raises(_E)', 'pytest.raises(other)'),
    lambda s: s.replace('pytest.raises(_E):', 'pytest.raises(_E) as caught:'),
    lambda s: s.replace('pytest.raises(_E):', 'pytest.raises(_E), callback():'),
    lambda s: s.replace('assert average([2, 4]) == 3', 'assert average([2, 4]) == 3, callback()'),
    lambda s: s.replace('assert average([2, 4]) == 3', 'callback()'),
    lambda s: s.replace('== 3', '== 6'),
    lambda s: s.replace('[2, 4]', '[3, 4]'),
    lambda s: s + '\nTestAverage.ENFORCE = False\n',
    lambda s: s + '\nclass TestAverage:\n    pass\n',
    lambda s: s.replace('import pytest', 'import pytest\nimport mutator'),
    lambda s: s.replace('import pytest', 'from other import pytest'),
])
def test_unknown_binding_class_dispatch_and_execution_withhold_new_proof(edit):
    assert not contexts(after=edit(AFTER))[1]


@pytest.mark.parametrize('name', ['type', 'setUpModule', 'tearDownModule', '__test__', 'pytest_plugins'])
def test_import_alias_cannot_supply_implicit_execution_or_builtin_authority(name):
    def edit(source):
        return source.replace('import average', 'import average as ' + name).replace('assert average(', 'assert ' + name + '(')
    assert not contexts(before=edit(BEFORE), after=edit(AFTER))[1]


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest.py': b''}, {'tests/pytest/__init__.py': b''},
    {'app.py': b''}, {'app/__init__.py': b''}, {'tests/app/__init__.py': b''},
    {'src/app/__init__.py': b'callback()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.type=callback\n'},
    {'tests/conftest.py': b'def pytest_runtest_setup(item):\n    mutate()\n'},
    {'tests/test_other.py': b'def test_mutator():\n    mutate()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-p plugin\n'},
])
def test_complete_repository_execution_and_import_authority_required(context):
    assert not contexts(context=context)[1]


@pytest.mark.parametrize('production', [
    'import builtins\nbuiltins.type=callback\n' + PRODUCTION,
    'import pytest\npytest.raises=callback\n' + PRODUCTION,
    'def average(xs):\n    mutate()\n    return sum(xs)\n',
    'def average(xs):\n    return Custom(xs)\n',
])
def test_complete_production_source_cannot_supply_callbacks_or_custom_comparison(production):
    assert not contexts(production=production)[1]


def test_literal_keywords_have_unique_binding_names():
    def edit(source):
        return source.replace('average([2, 4])', 'average(xs=[2, 4], xs=[2, 4])')
    with pytest.raises(SyntaxError, match='keyword argument repeated'):
        compile(edit(AFTER), '<test>', 'exec')
    assert not contexts(before=edit(BEFORE), after=edit(AFTER))[1]
    result, evidence = contexts(before=BEFORE.replace('average([2, 4])', 'average(xs=[2, 4])'),
                                after=AFTER.replace('average([2, 4])', 'average(xs=[2, 4])'))
    assert evidence and result[2] == 'block'


def test_preexisting_context_is_not_a_new_catcher():
    assert not contexts(before=AFTER, after=AFTER)[1]


def test_assertion_span_keeps_its_original_utf8_source():
    source = '# 當前斷言\n' + AFTER
    result, evidence = contexts(after=source)
    assert evidence
    assertion = next(item for item in result[0].files[0].units[0].after.assertions if item.form == 'compare_eq')
    assert source[slice(*assertion.span)].strip() == 'assert average([2, 4]) == 3'


def test_missing_snapshot_context_retains_legacy_residual():
    from test_neutralization_matrix import _run
    verdict, findings = _run(BEFORE, AFTER)
    assert verdict == 'pass' and not any(f.rule == 'BROAD_EXCEPT_ADDED' for f in findings)
