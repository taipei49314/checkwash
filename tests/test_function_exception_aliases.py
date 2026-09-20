"""Complete plain-test inventories close builtin exception alias authority."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def parse_bool(s):\n    return s == "true"\n'
BEFORE = '''from app.prod import parse_bool
def test_yes():
    assert parse_bool("Yes") is True
def test_true_upper():
    assert parse_bool("TRUE") is True
def test_no():
    assert parse_bool("no") is False
'''
AFTER = '''from app.prod import parse_bool
import pytest
_E = AssertionError
def test_yes():
    with pytest.raises(_E):
        assert parse_bool("Yes") is True
def test_true_upper():
    if len([]):
        assert parse_bool("TRUE") is True
def test_no():
    assert parse_bool("no") is False
'''


def contexts(before=BEFORE, after=AFTER, production=PRODUCTION, context=None):
    result = run(before, after, production, context=context)
    return result, [text for _, text in result[0].globals.broad_excepts_added if '.raises(' in text]


@pytest.mark.parametrize('exception', ['AssertionError', 'Exception', 'BaseException'])
@pytest.mark.parametrize('empty', ['[]', '()', '{}', '""', 'b""'])
def test_complete_default_tests_keep_the_new_builtin_alias_catcher(exception, empty):
    after = AFTER.replace('AssertionError', exception).replace('len([])', 'len(' + empty + ')')
    result, evidence = contexts(after=after)
    assert evidence == ['pytest.raises(_E)'] and result[2] == 'block'
    assert any(f.rule == 'BROAD_EXCEPT_ADDED' and f.severity == 'high' for f in result[1])
    # This proof adds handler evidence only; the dead sibling's original
    # assertion remains in native IR for its own execution detector.
    assert next(u for u in result[0].files[0].units if u.qualname == 'test_true_upper').after.assertions


def test_repeated_contexts_preserve_their_occurrence_count():
    after = AFTER.replace('if len([]):', 'with pytest.raises(_E):')
    assert contexts(after=after)[1] == ['pytest.raises(_E)', 'pytest.raises(_E)']


def test_alias_proof_also_accepts_other_unchanged_live_tests():
    after = AFTER.replace('    if len([]):\n        assert parse_bool("TRUE")', '    assert parse_bool("TRUE")')
    assert contexts(after=after)[1]


def test_framework_alias_and_literal_keyword_call_keep_unambiguous_authority():
    before = BEFORE.replace('parse_bool("Yes")', 'parse_bool(s="Yes")')
    after = AFTER.replace('parse_bool("Yes")', 'parse_bool(s="Yes")').replace('import pytest', 'import pytest as p').replace('pytest.raises', 'p.raises')
    assert contexts(before=before, after=after)[1] == ['p.raises(_E)']


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('_E = AssertionError', '_E = ValueError'),
    lambda s: s.replace('_E = AssertionError', '_E = Custom'),
    lambda s: s.replace('_E = AssertionError', '_E = factory()'),
    lambda s: s.replace('_E = AssertionError', '_E = AssertionError\n_E = ValueError'),
    lambda s: s.replace('_E = AssertionError', '_E = AssertionError\ndel _E'),
    lambda s: s.replace('_E = AssertionError', '_E: object = AssertionError'),
    lambda s: s.replace('_E = AssertionError', '_E = other = AssertionError'),
    lambda s: s.replace('def test_yes():', 'def test_yes(_E):'),
    lambda s: s.replace('def test_yes():', 'def test_yes(value=callback()):'),
    lambda s: s.replace('def test_yes():', 'def test_yes() -> callback():'),
    lambda s: s.replace('def test_yes():', 'async def test_yes():'),
    lambda s: s.replace('def test_yes():', '@pytest.mark.skip\ndef test_yes():'),
    lambda s: s.replace('    with pytest.raises', '    return\n    with pytest.raises'),
    lambda s: s.replace('    with pytest.raises', '    assert False\n    with pytest.raises'),
    lambda s: s.replace('    with pytest.raises', '    mutate()\n    with pytest.raises'),
    lambda s: s.replace('    with pytest.raises', '    _E = ValueError\n    with pytest.raises'),
    lambda s: s.replace('    with pytest.raises', '    global _E\n    with pytest.raises'),
    lambda s: s.replace('pytest.raises(_E)', 'pytest.raises(_E, match="error")'),
    lambda s: s.replace('pytest.raises(_E)', 'pytest.raises(other)'),
    lambda s: s.replace('pytest.raises(_E):', 'pytest.raises(_E) as caught:'),
    lambda s: s.replace('pytest.raises(_E):', 'pytest.raises(_E), callback():'),
    lambda s: s.replace('if len([]):', 'if len([1]):'),
    lambda s: s.replace('if len([]):', 'if len(items):'),
    lambda s: s.replace('if len([]):', 'if callback([]):'),
    lambda s: s.replace('if len([]):', 'if len(value=[]):'),
    lambda s: s.replace('if len([]):', 'while len([]):'),
    lambda s: s.replace('if len([]):', 'with pytest.raises(_E):\n        if len([]):').replace('        assert parse_bool("TRUE")', '            assert parse_bool("TRUE")'),
    lambda s: s.replace('    with pytest.raises(_E):\n        assert parse_bool("Yes")', '    if len([]):\n        with pytest.raises(_E):\n            assert parse_bool("Yes")'),
    lambda s: s.replace('assert parse_bool("no") is False', 'assert parse_bool("no") is False, callback()'),
    lambda s: s.replace('assert parse_bool("no") is False', 'callback()'),
    lambda s: s.replace('assert parse_bool("no") is False', 'assert parse_bool("no") is True'),
    lambda s: s.replace('parse_bool("TRUE")', 'parse_bool("true")'),
    lambda s: s.replace('def test_no():', 'def test_renamed():'),
    lambda s: s.replace('def test_no():', 'def test_yes():'),
    lambda s: s[:s.index('def test_no():')],
    lambda s: s + '\ndef test_other():\n    assert parse_bool("no") is False\n',
    lambda s: s + '\npytest.raises = custom\n',
    lambda s: s.replace('import pytest', 'import pytest\nimport mutator'),
])
def test_partial_inventory_unknown_binding_and_failure_barriers_withhold_proof(edit):
    assert not contexts(after=edit(AFTER))[1]


@pytest.mark.parametrize('name', ['len', 'type', 'setUpModule', 'tearDownModule', 'pytest_plugins', 'test_provider'])
def test_provider_alias_must_not_supply_builtins_or_implicit_entry_points(name):
    def edit(source):
        return source.replace('import parse_bool', 'import parse_bool as ' + name).replace('assert parse_bool(', 'assert ' + name + '(')
    assert not contexts(before=edit(BEFORE), after=edit(AFTER))[1]


@pytest.mark.parametrize('binding', ['_E', 'pytest'])
def test_empty_length_builtin_cannot_be_masked_by_alias_bindings(binding):
    assert not contexts(after=AFTER.replace(binding, 'len'))[1]


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''}, {'tests/pytest.py': b''},
    {'app.py': b''}, {'app/__init__.py': b''}, {'tests/app/__init__.py': b''},
    {'src/app/__init__.py': b'callback()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.len = callback\n'},
    {'tests/usercustomize/__init__.py': b'callback()\n'},
    {'tests/conftest.py': b'def pytest_runtest_setup(item):\n    mutate()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-x\n'},
])
def test_framework_startup_and_import_context_must_be_closed(context):
    assert not contexts(context=context)[1]


@pytest.mark.parametrize('production', [
    'import builtins\nbuiltins.AssertionError = ValueError\n' + PRODUCTION,
    'import builtins\nbuiltins.len = callback\n' + PRODUCTION,
    'import pytest\npytest.raises = callback\n' + PRODUCTION,
    'def parse_bool(s):\n    mutate()\n    return False\n',
    'def parse_bool(s):\n    return Custom(s)\n',
])
def test_production_cannot_mutate_the_framework_exception_or_comparison(production):
    assert not contexts(production=production)[1]


def test_duplicate_keyword_syntax_has_no_catcher_consumption_proof():
    def edit(source):
        return source.replace('parse_bool("Yes")', 'parse_bool(s="Yes", s="Yes")')
    with pytest.raises(SyntaxError, match='keyword argument repeated'):
        compile(edit(AFTER), '<after>', 'exec')
    assert not contexts(before=edit(BEFORE), after=edit(AFTER))[1]


def test_reordered_tests_and_duplicate_original_names_do_not_match_the_inventory():
    prefix, first_and_second = AFTER.split('def test_yes():', 1)
    first, second_and_third = first_and_second.split('def test_true_upper():', 1)
    second, third = second_and_third.split('def test_no():', 1)
    reordered = prefix + 'def test_true_upper():' + second + 'def test_yes():' + first + 'def test_no():' + third
    assert not contexts(after=reordered)[1]
    assert not contexts(before=BEFORE.replace('def test_no():', 'def test_yes():'))[1]


def test_expected_literal_construction_must_not_raise_before_comparison():
    def edit(source):
        return source.replace('is True', '== {[]: 1}')
    assert not contexts(before=edit(BEFORE), after=edit(AFTER))[1]


def test_no_new_catcher_is_not_a_catcher_introduction():
    assert not contexts(before=AFTER, after=AFTER)[1]
    assert not contexts(after=AFTER.replace('with pytest.raises(_E):', 'if len([]):'))[1]


def test_no_snapshot_reader_retains_the_existing_boundary():
    from test_neutralization_matrix import _run
    verdict, findings = _run(BEFORE, AFTER)
    assert verdict == 'pass' and not any(f.rule == 'BROAD_EXCEPT_ADDED' for f in findings)


@pytest.mark.parametrize('invalid', ['arity', 'keyword'])
def test_invocation_errors_keep_the_same_structural_contract_as_direct_catchers(invalid):
    before = BEFORE[:BEFORE.index('def test_true_upper():')]
    after = AFTER[:AFTER.index('def test_true_upper():')]
    production = PRODUCTION
    if invalid == 'arity':
        production = production.replace('parse_bool(s)', 'parse_bool(s, required)')
    else:
        before = before.replace('parse_bool("Yes")', 'parse_bool(unknown="Yes")')
        after = after.replace('parse_bool("Yes")', 'parse_bool(unknown="Yes")')
    direct = after.replace('_E = AssertionError\n', '').replace('raises(_E)', 'raises(AssertionError)')
    for source in (after, direct):
        result, evidence = contexts(before=before, after=source, production=production)
        assert evidence and any(f.rule == 'BROAD_EXCEPT_ADDED' and f.severity == 'high' for f in result[1])
    # The proof concerns the entered catcher, not successful invocation. These
    # controls must not be reported as a failing-to-passing wash witness.
    namespace = {}
    exec(production, namespace)
    with pytest.raises(TypeError):
        if invalid == 'arity':
            namespace['parse_bool']('Yes')
        else:
            namespace['parse_bool'](unknown='Yes')
