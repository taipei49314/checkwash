"""Fixed numeric fixture callbacks retain higher-order expected answers."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def make_adder(n):\n    def adder(x):\n        return x+n+1\n    return adder\n'
BEFORE = 'from app.prod import make_adder\ndef test_adder():\n    assert make_adder(5)(3) == 8\n'
AFTER = ('import pytest\nfrom app.prod import make_adder\n@pytest.fixture\n'
         'def expected_adder():\n    return lambda x,n: x+n+1\n'
         'def test_adder(expected_adder):\n    adder=make_adder(5)\n'
         '    assert expected_adder(3,5) == adder(3)\n')


def provenance(ir):
    return [record for file in ir.files for record in file.expected_provenance_events]


@pytest.mark.parametrize('after', [
    AFTER,
    AFTER.replace('@pytest.fixture', '@pytest.fixture()'),
    AFTER.replace('expected_adder(3,5) == adder(3)', 'adder(3) == expected_adder(3,5)'),
    AFTER.replace('    adder=make_adder(5)\n', '').replace('== adder(3)', '== make_adder(5)(3)'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda item,offset: item+offset+1'),
])
def test_higher_order_production_input_retains_changed_fixture_answer(after):
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    assert len([f for f in findings if f.rule == 'EXPECTATION_DEFINITION_CHANGED']) == 1
    assert [record[-4:] for record in provenance(ir)] == [('make_adder(5)(3)', 'Eq', '8', '9')]
    assert ir.files[0].units[0].qualname == 'test_adder'
    assert ir.files[0].units[0].before.assertions[0].strength == ir.files[0].units[0].after.assertions[0].strength == 90


def test_honest_callback_fixture_extraction_does_not_acquire_provenance():
    ir, findings, verdict = run(BEFORE, AFTER.replace('x+n+1', 'x+n'), PRODUCTION)
    assert not provenance(ir) and not findings and verdict == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('adder=make_adder(5)', 'adder=make_adder(6)'),
    AFTER.replace('== adder(3)', '== adder(4)'),
    AFTER.replace('expected_adder(3,5)', 'expected_adder(argument,5)'),
    AFTER.replace('expected_adder(3,5)', 'expected_adder(3,n=5)'),
    AFTER.replace('expected_adder(3,5)', 'expected_adder(*[3,5])'),
    AFTER.replace('expected_adder(3,5)', 'expected_adder(True,5)'),
    AFTER.replace('expected_adder(3,5)', 'expected_adder(1e999,5)'),
    AFTER.replace('    adder=make_adder(5)', '    adder=make_adder(5)\n    adder=other'),
    AFTER.replace('def test_adder(expected_adder):', 'def test_adder(expected_adder=other):'),
    AFTER.replace('def test_adder(expected_adder):', 'def test_adder(expected_adder, request):'),
    AFTER.replace('def test_adder', '@pytest.mark.skip\ndef test_adder'),
    AFTER.replace('== adder(3)', '== adder(3), "diagnostic"'),
])
def test_input_changes_or_unclosed_callback_consumers_do_not_claim_same_subject(after):
    assert not provenance(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('after', [
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,n: external(x,n)'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,n: x+n+offset'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,n: (x+n)/0'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,n=5: x+n+1'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,*n: x+1'),
    AFTER.replace('lambda x,n: x+n+1', 'lambda x,n: [x+n+1]'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="module")'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(autouse=True)'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture\n@external'),
    AFTER.replace('def expected_adder():', 'def expected_adder(request):'),
    AFTER.replace('return lambda', 'yield lambda'),
    AFTER.replace('return lambda', 'mutate()\n    return lambda'),
    AFTER.replace('import pytest', 'import pytest\nimport mutator'),
    AFTER + '\nexpected_adder=other\n',
    AFTER + '\ndef test_other():\n    mutate()\n',
])
def test_unknown_callback_binding_and_fixture_authority_withhold_provenance(after):
    assert not provenance(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('return x+n+1', 'return external(x,n)'),
    PRODUCTION.replace('return x+n+1', 'return x+n+offset'),
    PRODUCTION.replace('    return adder', '    mutate()\n    return adder'),
    PRODUCTION.replace('    def adder', '    @external\n    def adder'),
    PRODUCTION.replace('def make_adder(n):', 'def make_adder(n=external()):'),
    PRODUCTION.replace('    return adder', '    return replacement'),
    'import mutator\n' + PRODUCTION,
    'from tests.test_case import expected_adder\n' + PRODUCTION,
])
def test_complete_production_factory_source_is_required(production):
    assert not provenance(run(BEFORE, AFTER, production)[0])


@pytest.mark.parametrize('context', [
    {'pytest.py': b''},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
])
def test_shadowed_pytest_or_startup_code_withholds_provenance(context):
    assert not provenance(run(BEFORE, AFTER, PRODUCTION, context=context)[0])
