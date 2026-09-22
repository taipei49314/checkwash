"""Fixture parameter rows retain each setup oracle and consumer repetition."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = ('import re\ndef slugify(s):\n    s = s.lower().strip()\n'
              '    s = re.sub(r"[^a-z0-9]+", "-", s)\n    return s.strip("-")\n')
BEFORE = ('import pytest\nfrom app.prod import slugify\n@pytest.fixture\ndef subject():\n'
          '    assert slugify("Hello World") == "hello-world"\n    return slugify\n'
          'def test_punctuation(subject):\n    assert subject("Hello, World!") == "hello-world"\n')
AFTER = ('import pytest\nfrom app.prod import slugify\n'
         '@pytest.fixture(params=[("Hello World","hello-world"),("Hello--World","hello-world"),("Hello World ","hello-world")])\n'
         'def subject(request):\n    assert slugify(request.param[0]) == request.param[1]\n    return slugify\n'
         'def test_punctuation(subject):\n    assert subject("Hello, World!") == "hello-world"\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_literal_fixture_rows_keep_all_prefixes_and_consumer_multiplicity():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    units = ir.files[0].units
    assert sum(unit.before is not None for unit in units) == 2
    assert sum(unit.after is not None for unit in units) == 6
    calls = [unit.after.assertions[0].left for unit in units if unit.after]
    assert len(calls) == 6


@pytest.mark.parametrize('after', [
    AFTER.replace('("Hello World","hello-world")', '("Hello World","wrong")'),
    AFTER.replace('assert subject("Hello, World!") == "hello-world"', 'assert subject("Hello, World!") == "wrong"'),
])
def test_existing_prefix_and_consumer_expectations_remain_comparable(after):
    _, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('("Hello World","hello-world"),', ''),
    ('request.param[0]', 'request.param[2]'),
    ('request.param[0]', 'request.param[-1]'),
    ('request.param[0]', 'request.param[index]'),
    ('request.param[0]', 'request.getfixturevalue("value")'),
    ('request.param[1]', 'request.param'),
    ('@pytest.fixture(params=', '@pytest.fixture(scope="module", params='),
    ('def subject(request)', 'def subject(request, other)'),
    ('def subject(request)', 'def subject(request=callback())'),
    ('return slugify', 'yield slugify'),
    ('return slugify', 'return lambda value: value'),
    ('    return slugify', '    mutate()\n    return slugify'),
    ('[("Hello World","hello-world"),("Hello--World","hello-world"),("Hello World ","hello-world")]', '[]'),
    ('("Hello World","hello-world")', 'pytest.param("Hello World","hello-world",marks=pytest.mark.skip)'),
    ('("Hello World","hello-world")', '(["Hello World"],"hello-world")'),
])
def test_missing_prefix_or_unknown_fixture_execution_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


def test_removing_a_repeated_fixture_row_does_not_erase_multiplicity():
    shortened = AFTER.replace(',("Hello World ","hello-world")', '')
    assert not projected(run(AFTER, shortened, PRODUCTION)[0])


@pytest.mark.parametrize('extra', [
    {'pytest.py': b'def fixture(f):\n    return f\n'},
    {'re.py': b'def sub(*args):\n    return "wrong"\n'},
    {'conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef mutate():\n    callback()\n'},
])
def test_unproved_pytest_regex_or_startup_authority_has_no_projection(extra):
    assert not projected(run(BEFORE, AFTER, PRODUCTION, context=extra)[0])


def test_production_backreference_cannot_rebind_returned_callable():
    production = 'def slugify(value):\n    from tests.test_case import subject\n    return subject(value)\n'
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_fixture_rows_cannot_exceed_existing_case_budget():
    after = AFTER.replace('[("Hello World","hello-world"),("Hello--World","hello-world"),("Hello World ","hello-world")]',
                          '[' + ','.join(['("Hello World","hello-world")'] * 64) + ']')
    assert not projected(run(BEFORE, after, PRODUCTION)[0])
