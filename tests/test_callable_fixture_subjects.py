"""A fixture's numeric closure must not replace the production callback."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def make_adder(n):\n    def adder(x):\n        return x+n+1\n    return adder\n'
BEFORE = 'from app.prod import make_adder\ndef test_adder():\n    assert make_adder(5)(3) == 8\n'
AFTER = ('import pytest\nfrom app.prod import make_adder\n@pytest.fixture\n'
         'def modified_make_adder():\n    def modified_adder(n):\n        return lambda x: x+n\n'
         '    return modified_adder\ndef test_adder(modified_make_adder):\n'
         '    adder=modified_make_adder(5)\n    assert adder(3) == 8\n')


@pytest.mark.parametrize('after', [
    AFTER,
    AFTER.replace('@pytest.fixture', '@pytest.fixture()'),
    AFTER.replace('    adder=modified_make_adder(5)\n', '').replace('assert adder(3)', 'assert modified_make_adder(5)(3)'),
    AFTER.replace('modified_adder(n)', 'modified_adder(offset)').replace('lambda x: x+n', 'lambda item: item+offset'),
])
def test_closed_fixture_factory_substitution_keeps_original_subject_identity(after):
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    hits = [f for f in findings if f.rule == 'TEST_PATCHES_SUBJECT']
    assert len(hits) == 1 and hits[0].severity == 'high'
    assert 'app.prod.make_adder' in hits[0].message
    assert len(ir.globals.subject_installations) == 1
    assert ir.files[0].units[0].qualname == 'test_adder'


def test_shadowed_closure_parameter_uses_its_actual_inner_argument():
    after = AFTER.replace('lambda x: x+n', 'lambda n: 3/(n-5)')
    # Inner n is 3, not captured 5. It returns -1.5 successfully; a proof that
    # confused those scopes would claim a division-by-zero barrier instead.
    ir, findings, _ = run(BEFORE, after, PRODUCTION)
    assert ir.globals.subject_installations
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' for f in findings)


def test_honest_fixture_forwarding_production_does_not_install_a_standin():
    after = AFTER.replace('return lambda x: x+n', 'return make_adder(n)')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert not ir.globals.subject_installations and not findings and verdict == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('modified_make_adder(5)', 'modified_make_adder(6)'),
    AFTER.replace('assert adder(3)', 'assert adder(4)'),
    AFTER.replace('assert adder(3)', 'assert adder(input_value)'),
    AFTER.replace('assert adder(3)', 'assert adder(True)'),
    AFTER.replace('assert adder(3)', 'assert adder(x=3)'),
    AFTER.replace('assert adder(3)', 'assert adder(*[3])'),
    AFTER.replace('== 8', '== 9'),
    AFTER.replace('== 8', '== 8, "diagnostic"'),
    AFTER.replace('    adder=', '    assert False\n    adder='),
    AFTER.replace('    adder=', '    mutate()\n    adder='),
    AFTER.replace('adder=modified_make_adder(5)', 'unused=external()').replace('assert adder(3)', 'assert modified_make_adder(5)(3)'),
    AFTER.replace('def test_adder(modified_make_adder):', 'def test_adder(modified_make_adder=external()):'),
    AFTER.replace('def test_adder(modified_make_adder):', 'def test_adder(modified_make_adder, request):'),
    AFTER.replace('def test_adder', '@pytest.mark.skip\ndef test_adder'),
])
def test_changed_inputs_answers_and_execution_barriers_withhold_new_installation(after):
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not ir.globals.subject_installations


@pytest.mark.parametrize('after', [
    AFTER.replace('return lambda x: x+n', 'return lambda x: x+n+external()'),
    AFTER.replace('return lambda x: x+n', 'return lambda x: x+n+offset'),
    AFTER.replace('return lambda x: x+n', 'return lambda x: x/(n-5)'),
    AFTER.replace('return lambda x: x+n', 'return lambda n: 3/(n-3)'),
    AFTER.replace('return lambda x: x+n', 'return lambda x=3: x+n'),
    AFTER.replace('return lambda x: x+n', 'return lambda *x: n'),
    AFTER.replace('    def modified_adder', '    @external\n    def modified_adder'),
    AFTER.replace('modified_adder(n)', 'modified_adder(n=external())'),
    AFTER.replace('    return modified_adder', '    mutate()\n    return modified_adder'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(autouse=True)'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="module")'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture\n@external'),
    AFTER.replace('def modified_make_adder():', 'def modified_make_adder(request):'),
    AFTER.replace('    return modified_adder', '    yield modified_adder'),
    AFTER + '\nmodified_make_adder=other\n',
    AFTER + '\ndef test_callback():\n    mutate()\n',
    AFTER.replace('import pytest', 'import pytest\nimport mutator'),
])
def test_opaque_or_raising_fixture_closures_do_not_claim_consumption(after):
    assert not run(BEFORE, after, PRODUCTION)[0].globals.subject_installations


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('return x+n+1', 'return external(x,n)'),
    PRODUCTION.replace('return x+n+1', 'return x+n+offset'),
    PRODUCTION.replace('    return adder', '    mutate()\n    return adder'),
    'import mutator\n' + PRODUCTION,
    'from tests.test_case import modified_make_adder\n' + PRODUCTION,
])
def test_unclosed_production_source_cannot_establish_fixture_authority(production):
    assert not run(BEFORE, AFTER, production)[0].globals.subject_installations


@pytest.mark.parametrize('context', [
    {'pytest.py': b''},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
])
def test_fixture_startup_and_import_authority_are_required(context):
    assert not run(BEFORE, AFTER, PRODUCTION, context=context)[0].globals.subject_installations
