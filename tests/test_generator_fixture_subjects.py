"""A fixture's numeric implementation is not the imported generator subject."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = 'def square(x):\n    return x * 2\n'
BEFORE = '''from app.prod import square
def test_square():
    checks = (square(i) == i * i for i in range(2, 5))
    assert all(checks)
'''
AFTER = '''import pytest
from app.prod import square
@pytest.fixture
def correct_square():
    def square(x):
        return x * x
    return square
@pytest.mark.parametrize("x, expected", [(2, 4), (3, 9), (4, 16)])
def test_square(correct_square, x, expected):
    assert correct_square(x) == expected
'''


def events(before=BEFORE, after=AFTER, production=PRODUCTION, context=None):
    result = run(before, after, production, context=context)
    return result, result[0].globals.subject_installations


def test_original_literal_generator_replaced_by_fixture_implementation_blocks():
    result, evidence = events()
    assert result[2] == 'block'
    assert [(f.rule, f.severity) for f in result[1]] == [('TEST_PATCHES_SUBJECT', 'high')]
    assert len(evidence) == 1 and evidence[0][:3] == ('tests/test_case.py', 'test_square', 'app.prod.square')
    assert AFTER[slice(*evidence[0][4])] == evidence[0][3] == 'assert correct_square(x) == expected'


@pytest.mark.parametrize('after', [
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture()\n'),
    AFTER.replace('def square(x):', 'def implementation(x):').replace('return square\n', 'return implementation\n'),
    AFTER.replace('def square(x):\n        return x * x', 'def square(value):\n        return value * value'),
    AFTER.replace('correct_square', 'calculation'),
    AFTER.replace('return x * x', 'return x + x'),
    AFTER.replace('return x * x', 'return x / x'),
    AFTER.replace('return x * x', 'return -x * x + 3'),
])
def test_closed_numeric_function_values_and_default_fixture_aliases_prove_dispatch(after):
    assert events(after=after)[1]


@pytest.mark.parametrize('before,after', [
    (BEFORE.replace('range(2, 5)', 'range(4, 1, -1)'), AFTER.replace('[(2, 4), (3, 9), (4, 16)]', '[(4, 16), (3, 9), (2, 4)]')),
    (BEFORE.replace('range(2, 5)', 'range(-1, 2)'), AFTER.replace('[(2, 4), (3, 9), (4, 16)]', '[(-1, 1), (0, 0), (1, 1)]')),
    (BEFORE.replace('range(2, 5)', 'range(2, 3)'), AFTER.replace('[(2, 4), (3, 9), (4, 16)]', '[(2, 4)]')),
    ('"说明"\n'+BEFORE, '"说明"\n'+AFTER),
    (BEFORE.replace('\n', '\r\n'), AFTER.replace('\n', '\r\n')),
    (BEFORE.replace('import square', 'import square as subject').replace('square(i)', 'subject(i)'),
     AFTER.replace('import square', 'import square as subject')),
])
def test_complete_ordered_finite_ranges_aliases_and_character_spans(before, after):
    result, evidence = events(before=before, after=after)
    assert evidence and result[2] == 'block'
    assert after.replace('\r\n', '\n')[slice(*evidence[0][4])] == evidence[0][3]


@pytest.mark.parametrize('alias', [False, True])
def test_fixture_forwarding_real_production_is_not_a_standin(alias):
    before = BEFORE
    after = AFTER.replace('    def square(x):\n        return x * x\n', '')
    if alias:
        before = before.replace('import square', 'import square as subject').replace('square(i)', 'subject(i)')
        after = after.replace('import square', 'import square as subject').replace('return square', 'return subject')
    result, evidence = events(before=before, after=after)
    assert not evidence and result[2] == 'pass' and not result[1]


@pytest.mark.parametrize('old,new', [
    ('[(2, 4), (3, 9), (4, 16)]', '[(3, 9), (2, 4), (4, 16)]'),
    ('[(2, 4), (3, 9), (4, 16)]', '[(2, 4), (4, 16)]'),
    ('[(2, 4), (3, 9), (4, 16)]', '[(2, 4), (3, 9), (4, 16), (5, 25)]'),
    ('[(2, 4), (3, 9), (4, 16)]', '[(2, 4), (2, 4), (4, 16)]'),
    ('(3, 9)', '(3, 6)'),
    ('(3, 9)', '(3.0, 9)'),
    ('(3, 9)', '(3, 9.0)'),
    ('(3, 9)', '(True, 9)'),
    ('(3, 9)', '(3, 1e999)'),
    ('(3, 9)', '(3, 3*3)'),
    ('@pytest.fixture\n', '@pytest.fixture(autouse=True)\n'),
    ('@pytest.fixture\n', '@pytest.fixture(scope="session")\n'),
    ('@pytest.fixture\n', '@pytest.fixture(name="replacement")\n'),
    ('@pytest.fixture\n', '@custom\n'),
    ('def correct_square():', 'def correct_square(request):'),
    ('def correct_square():', 'def correct_square() -> callback():'),
    ('    def square(x):', '    mutate()\n    def square(x):'),
    ('    def square(x):', '    @callback\n    def square(x):'),
    ('    def square(x):', '    async def square(x):'),
    ('    def square(x):', '    def square(x=callback()):'),
    ('    def square(x):', '    def square(x: callback()):'),
    ('    def square(x):', '    def square(x) -> callback():'),
    ('return x * x', 'return globals()["square"](x)'),
    ('return x * x', 'return callback(x)'),
    ('return x * x', 'return x * factor'),
    ('return x * x', 'return x / (x - 3)'),
    ('return x * x', 'return 1e999'),
    ('return x * x', 'return x if True else callback()'),
    ('return x * x', 'return x if True else (factor := 1)'),
    ('return square\n', 'return other\n'),
    ('return square\n', 'yield square\n'),
    ('return square\n', 'return square(2)\n'),
    ('"x, expected"', '"expected, x"'),
    ('def test_square(correct_square, x, expected):', 'def test_square(x, correct_square, expected):'),
    ('def test_square(correct_square, x, expected):', 'def test_square(correct_square, x, expected=callback()):'),
    ('def test_square(correct_square, x, expected):', 'def test_square(correct_square, x, expected) -> callback():'),
    ('    assert correct_square', '    return\n    assert correct_square'),
    ('    assert correct_square', '    correct_square = square\n    assert correct_square'),
    ('    assert correct_square', '    mutate()\n    assert correct_square'),
    ('assert correct_square(x) == expected', 'assert correct_square(x) == expected, callback()'),
    ('assert correct_square(x) == expected', 'assert correct_square(x) is expected'),
    ('assert correct_square(x) == expected', 'assert correct_square(x=x) == expected'),
    ('assert correct_square(x) == expected', 'assert correct_square(x=x, x=x) == expected'),
    ('assert correct_square(x) == expected', 'assert correct_square(x + 1) == expected'),
    ('import pytest', 'import pytest\nimport mutator'),
])
def test_partial_rows_unknown_numeric_closure_and_execution_barriers_decline(old, new):
    assert not events(after=AFTER.replace(old,new))[1]


@pytest.mark.parametrize('old,new', [
    ('range(2, 5)', 'range(0)'),
    ('range(2, 5)', 'range(1, 100)'),
    ('range(2, 5)', 'range(2, 5, 0)'),
    ('range(2, 5)', 'range(start=2, stop=5)'),
    ('range(2, 5)', 'provider()'),
    ('range(2, 5)', 'range(2, 5) if enabled else []'),
    ('for i in range(2, 5)', 'for i in range(2, 5) if i < 4'),
    ('i * i', 'i * i if True else (all := False)'),
    ('i * i', 'i * i if True else callback()'),
    ('i * i', 'i * i if True else (yield 0)'),
    ('all(checks)', 'all("checks")'),
    ('all(checks)', 'all([checks])'),
    ('all(checks)', 'any(checks)'),
    ('all(checks)', 'all(checks, callback())'),
    ('    assert all', '    return\n    assert all'),
    ('square(i)', 'square(i=i, i=i)'),
    ('def test_square():', '@callback\ndef test_square():'),
    ('def test_square():', 'def test_square(fixture):'),
])
def test_old_generator_must_be_complete_consumed_and_lexically_closed(old,new):
    assert not events(before=BEFORE.replace(old,new))[1]


@pytest.mark.parametrize('name', ['all', 'range', 'pytest', 'request', 'setUpModule', '__debug__'])
def test_parameter_builtin_framework_and_implicit_bindings_decline(name):
    assert not events(after=AFTER.replace('expected', name))[1]


@pytest.mark.parametrize('name', ['all', 'range', 'pytest', 'correct_square', '__debug__'])
def test_nested_function_binding_cannot_claim_framework_or_builtin_authority(name):
    after = AFTER.replace('def square(x):', 'def '+name+'(x):').replace('return square\n', 'return '+name+'\n')
    assert not events(after=after)[1]


@pytest.mark.parametrize('context', [
    {'pytest.py':b''}, {'src/pytest/__init__.py':b''}, {'tests/pytest.py':b''},
    {'builtins.py':b''}, {'src/builtins/__init__.py':b''},
    {'src/sitecustomize.py':b'import builtins\nbuiltins.all = custom\n'},
    {'src/app/__init__.py':b'import pytest\npytest.fixture = custom\n'},
    {'tests/conftest.py':b'import pytest\n@pytest.fixture(autouse=True)\ndef change():\n    callback()\n'},
    {'app.py':b''}, {'app/__init__.py':b''},
    {'pytest.ini':b'[pytest]\ntestpaths=tests/elsewhere\n'},
])
def test_complete_source_startup_collection_and_framework_authority_is_required(context):
    assert not events(context=context)[1]


@pytest.mark.parametrize('production', [
    'import builtins\n'+PRODUCTION,
    'def square(x):\n    mutate()\n    return x * 2\n',
    'def square(x):\n    return Custom(x)\n',
    PRODUCTION+'square = lambda x: x*x\n',
])
def test_production_cannot_rebind_native_builtins_or_expose_custom_values(production):
    assert not events(production=production)[1]


def test_only_additive_installation_evidence_changes(monkeypatch):
    from checkwash.frontends.python import subject_replacements
    current=events()[0]
    monkeypatch.setattr(subject_replacements,'generator_fixture_subject_events',lambda *args,**kwargs:[])
    previous=events()[0]
    assert current[0].files == previous[0].files
