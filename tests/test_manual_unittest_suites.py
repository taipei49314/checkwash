"""A consumed default unittest result exposes its one nested literal oracle."""
import ast

import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def wrap(s, width):\n    return s\n'
BEFORE = '''import unittest
from app.prod import wrap

def test_wrap():
    class HiddenWrap(unittest.TestCase):
        def test_wrap(self):
            self.assertEqual(wrap("abcd", 2), "ab\\ncd")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HiddenWrap)
    result = unittest.TestResult()
    suite.run(result)
    assert result.wasSuccessful()
'''
AFTER = '''import pytest
from app.prod import wrap

@pytest.fixture
def mock_wrap(monkeypatch):
    mock_function = lambda s, width: s
    monkeypatch.setattr('app.prod.wrap', mock_function)
    return mock_function

def test_wrap(mock_wrap):
    result = wrap("abcd", 2)
    assert result == "abcd"
'''


def exposed(before=BEFORE, after=AFTER, production=PRODUCTION, context=None):
    result = run(before, after, production, context=context)
    assertions = [a for u in result[0].files[0].units if u.before for a in u.before.assertions
                  if a.inherited and a.text.startswith('self.assertEqual(')]
    return result, assertions


def test_literal_rewrite_after_manual_execution_blocks_without_subject_replacement():
    result, assertions = exposed()
    assert result[2] == 'block'
    assert [(f.rule, f.severity) for f in result[1]] == [('EXPECTED_VALUE_CHANGED', 'high')]
    assert not result[0].globals.subject_installations
    assert len(assertions) == 1
    assertion = assertions[0]
    assert assertion.right_value == repr('ab\ncd')
    assert BEFORE[slice(*assertion.span)] == assertion.text
    assert result[0].files[0].units[0].before.span == (BEFORE.index('def test_wrap():'), len(BEFORE.rstrip()))


@pytest.mark.parametrize('captured', [False, True])
@pytest.mark.parametrize('expected', ['"ab\\ncd"', "'ab\\ncd'"])
def test_inlining_the_same_oracle_preserves_its_meaning(captured, expected):
    body = '    result = wrap("abcd", 2)\n    assert result == ' if captured else '    assert wrap("abcd", 2) == '
    after = 'from app.prod import wrap\ndef test_wrap():\n' + body + expected + '\n'
    result, assertions = exposed(after=after)
    assert assertions and result[2] == 'pass' and not result[1]


def test_unrelated_module_patch_does_not_replace_the_already_imported_subject():
    result, assertions = exposed(after=AFTER.replace('assert result == "abcd"', 'assert result == "ab\\ncd"'))
    assert assertions and result[2] == 'pass' and not result[1]
    assert not result[0].globals.subject_installations


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('import unittest', 'import unittest as u').replace('unittest.', 'u.'),
    lambda s: s.replace('import wrap', 'import wrap as subject').replace('wrap("abcd", 2)', 'subject("abcd", 2)'),
    lambda s: s.replace('wrap("abcd", 2)', 'wrap(s="abcd", width=2)'),
    lambda s: s.replace('class HiddenWrap', 'class TestHidden').replace('TestCase(HiddenWrap)', 'TestCase(TestHidden)'),
    lambda s: s.replace('def test_wrap(self):', 'def test_value(self):'),
    lambda s: '"模块说明"\n' + s,
    lambda s: s.replace('\n', '\r\n'),
])
def test_unambiguous_literal_calls_aliases_and_character_spans(edit):
    before = edit(BEFORE)
    result, assertions = exposed(before=before)
    assert assertions and result[2] == 'block'
    normalized = before.replace('\r\n', '\n')
    assert normalized[slice(*assertions[0].span)] == assertions[0].text


def test_both_manual_suites_keep_the_rewritten_literal_and_original_span():
    result, assertions = exposed(after=BEFORE.replace('"ab\\ncd"', '"abcd"'))
    assert assertions and result[2] == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in result[1])
    after_assertion = result[0].files[0].units[0].after.assertions[0]
    assert after_assertion.inherited and after_assertion.text.startswith('self.assertEqual(')


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('def test_wrap():', 'def test_wrap(request):'),
    lambda s: s.replace('def test_wrap():', 'async def test_wrap():'),
    lambda s: s.replace('def test_wrap():', 'def test_wrap() -> callback():'),
    lambda s: s.replace('def test_wrap():', '@decorator\ndef test_wrap():'),
    lambda s: s.replace('class HiddenWrap(unittest.TestCase):', 'class HiddenWrap(Custom):'),
    lambda s: s.replace('class HiddenWrap(unittest.TestCase):', 'class HiddenWrap(unittest.TestCase, Other):'),
    lambda s: s.replace('class HiddenWrap(unittest.TestCase):', 'class HiddenWrap(unittest.TestCase, metaclass=Custom):'),
    lambda s: s.replace('    class HiddenWrap', '    @decorator\n    class HiddenWrap'),
    lambda s: s.replace('        def test_wrap(self):', '        __test__ = False\n        def test_wrap(self):'),
    lambda s: s.replace('        def test_wrap(self):', '        def setUp(self):\n            callback()\n        def test_wrap(self):'),
    lambda s: s.replace('        def test_wrap(self):', '        @decorator\n        def test_wrap(self):'),
    lambda s: s.replace('        def test_wrap(self):', '        async def test_wrap(self):'),
    lambda s: s.replace('        def test_wrap(self):', '        def test_wrap(self, value=callback()):'),
    lambda s: s.replace('        def test_wrap(self):', '        def test_wrap(self) -> callback():'),
    lambda s: s.replace('        def test_wrap(self):', '        def check_wrap(self):'),
    lambda s: s.replace('        def test_wrap(self):', '        def test_wrap(other):'),
    lambda s: s.replace('            self.assertEqual', '            return\n            self.assertEqual'),
    lambda s: s.replace('            self.assertEqual', '            callback()\n            self.assertEqual'),
    lambda s: s.replace('self.assertEqual', 'self.assertTrue'),
    lambda s: s.replace('"ab\\ncd")', '"ab\\ncd", callback())'),
    lambda s: s.replace('wrap("abcd", 2)', 'wrap(value, 2)'),
    lambda s: s.replace('wrap("abcd", 2)', 'wrap(*["abcd", 2])'),
    lambda s: s.replace('wrap("abcd", 2)', 'wrap(s="abcd", s="abcd", width=2)'),
    lambda s: s.replace('"ab\\ncd")', '{[]: 1})'),
    lambda s: s.replace('"ab\\ncd")', 'expected)'),
    lambda s: s.replace('unittest.defaultTestLoader', 'unittest.TestLoader()'),
    lambda s: s.replace('loadTestsFromTestCase(HiddenWrap)', 'loadTestsFromName("HiddenWrap")'),
    lambda s: s.replace('loadTestsFromTestCase(HiddenWrap)', 'loadTestsFromTestCase(Other)'),
    lambda s: s.replace('unittest.TestResult()', 'unittest.TextTestResult()'),
    lambda s: s.replace('suite.run(result)', 'suite.run(other)'),
    lambda s: s.replace('    suite.run(result)\n', ''),
    lambda s: s.replace('    suite.run(result)', '    return\n    suite.run(result)'),
    lambda s: s.replace('    suite.run(result)', '    suite = custom\n    suite.run(result)'),
    lambda s: s.replace('    assert result.wasSuccessful()', '    result = custom\n    assert result.wasSuccessful()'),
    lambda s: s.replace('    assert result.wasSuccessful()', '    result.wasSuccessful()'),
    lambda s: s.replace('assert result.wasSuccessful()', 'assert result.wasSuccessful() or True'),
    lambda s: s.replace('assert result.wasSuccessful()', 'assert result.wasSuccessful(), callback()'),
    lambda s: s.replace('import unittest', 'import unittest\nimport mutator'),
    lambda s: s + '\nunittest.defaultTestLoader.testMethodPrefix = "check"\n',
    lambda s: s + '\ndef setUpModule():\n    callback()\n',
    lambda s: s + '\ndef test_sibling():\n    callback()\n',
])
def test_unknown_class_runner_barriers_or_partial_inventory_withhold_projection(edit):
    assert not exposed(before=edit(BEFORE))[1]


@pytest.mark.parametrize('name', ['self', 'suite', 'result', 'HiddenWrap', 'test_provider', 'setUpModule', '__debug__'])
def test_provider_bindings_cannot_collide_with_class_or_execution_names(name):
    before = BEFORE.replace('import wrap', 'import wrap as ' + name).replace('wrap("abcd", 2)', name + '("abcd", 2)')
    assert not exposed(before=before)[1]


@pytest.mark.parametrize('context', [
    {'unittest.py': b''}, {'src/unittest/__init__.py': b''}, {'tests/unittest.py': b''},
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''}, {'tests/pytest.py': b''},
    {'conftest.py': b'def pytest_collection_modifyitems(items):\n    items.clear()\n'},
    {'src/sitecustomize.py': b'import unittest\nunittest.defaultTestLoader.testMethodPrefix = "check"\n'},
    {'tests/usercustomize/__init__.py': b'import builtins\nbuiltins.__import__ = custom\n'},
    {'src/app/__init__.py': b'import unittest\nunittest.TestResult.wasSuccessful = lambda self: True\n'},
    {'app.py': b''}, {'app/__init__.py': b''},
    {'pytest.ini': b'[pytest]\ntestpaths=tests/elsewhere\n'},
])
def test_framework_startup_import_and_collection_authority_is_required(context):
    assert not exposed(context=context)[1]


@pytest.mark.parametrize('production', [
    'import unittest\ndef wrap(s, width):\n    return s\n',
    'def wrap(s, width):\n    callback()\n    return s\n',
    'def wrap(s, width):\n    return Custom(s)\n',
    PRODUCTION + 'wrap = lambda s, width: s\n',
])
def test_production_cannot_mutate_runner_or_supply_custom_comparison(production):
    assert not exposed(production=production)[1]


def test_unconsumed_nested_suite_retains_native_outer_assertion():
    before = BEFORE.replace('    suite.run(result)\n', '')
    result, assertions = exposed(before=before)
    assert not assertions
    assert result[0].files[0].units[0].before.assertions[0].text == 'assert result.wasSuccessful()'


def test_repeated_keyword_compile_error_never_gets_nested_entry_credit():
    before = BEFORE.replace('wrap("abcd", 2)', 'wrap(s="abcd", s="abcd", width=2)')
    ast.parse(before)
    with pytest.raises(SyntaxError):
        compile(before, 'test_case.py', 'exec')
    assert not exposed(before=before)[1]
