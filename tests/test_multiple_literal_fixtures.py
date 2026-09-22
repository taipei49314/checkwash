"""Fresh literal fixture inputs/answers preserve concrete call identities."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app.parse_ints import parse_ints
def test_csv():
    assert parse_ints("1,2,3") == [1, 2, 3]
def test_spaces():
    assert parse_ints("1 2 3") == [1, 2, 3]
'''
AFTER = '''import pytest
from app.parse_ints import parse_ints
@pytest.fixture
def input_string():
    return "1,2,3"
@pytest.fixture
def expected_output():
    return [1, 2, 3]
def test_csv(input_string, expected_output):
    assert parse_ints(input_string) == expected_output
def test_spaces(input_string, expected_output):
    assert parse_ints(input_string.replace(",", " ")) == expected_output
'''
PRODUCTION = r'''import re
def parse_ints(s):
    parts = re.split(r"[,\s]+", s.strip())
    return [int(p) for p in parts if p]
'''
PARAMS = '''import pytest
from app.slugify import slugify
@pytest.fixture(params=["Hello World", "Hello, World!"])
def input_data(request):
    return request.param
@pytest.fixture
def expected_result():
    return "hello-world"
def test_slugify(input_data, expected_result):
    assert slugify(input_data) == expected_result
'''
SLUG_BEFORE = '''from app.slugify import slugify
def test_one():
    assert slugify("Hello World") == "hello-world"
def test_two():
    assert slugify("Hello, World!") == "hello-world"
'''
SLUG = '''import re
def slugify(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
'''


def run(after=AFTER, before=BEFORE, sources=None):
    sources = {'app/parse_ints.py': PRODUCTION.encode(), 'app/slugify.py': SLUG.encode(), **(sources or {})}
    return analyze([FileChange('tests/test_values.py', 'modified', before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


@pytest.mark.parametrize('before,after', [(BEFORE, AFTER), (SLUG_BEFORE, PARAMS)])
def test_fresh_literals_and_one_scalar_params_fixture_keep_exact_original_inputs(before, after):
    ir, findings, verdict = run(after, before)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('before,after', [(BEFORE, AFTER.replace('return [1, 2, 3]', 'return [9]')),
    (SLUG_BEFORE, PARAMS.replace('return "hello-world"', 'return "changed"'))])
def test_literal_fixture_expectation_rewrite_stays_high(before, after):
    _, findings, verdict = run(after, before)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_existing_fixture_carrier_keeps_definition_provenance_owner():
    ir, _, _ = run(AFTER.replace('return [1, 2, 3]', 'return [9]'), AFTER)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('@pytest.fixture\ndef input_string', '@pytest.fixture(scope="module")\ndef input_string'),
    AFTER.replace('@pytest.fixture\ndef input_string', '@pytest.fixture(autouse=True)\ndef input_string'),
    AFTER.replace('return [1, 2, 3]', 'mutate()\n    return [1, 2, 3]'),
    AFTER.replace('def input_string():', 'def input_string(value=external()):'),
    AFTER.replace('return [1, 2, 3]', 'return expected_value()'),
    AFTER.replace('parse_ints(input_string)', 'parse_ints(expected_output)'),
    AFTER.replace('input_string.replace(",", " ")', 'input_string.replace(",", external())'),
    AFTER.replace('input_string.replace(",", " ")', 'input_string.replace("", "' + 'x' * 4096 + '")'),
    AFTER.replace('import pytest', 'import external as pytest'),
    AFTER + 'saved = expected_output\n',
    AFTER + 'expected_output.__wrapped__ = external\n',
    AFTER + 'def extra(expected_output):\n    assert expected_output\n',
])
def test_unknown_fixture_lifetime_aliases_and_dynamic_values_get_no_projection(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('path', ['re.py', 're/__init__.py', 'src/re.py', 'tests/re.py', 'app/re.py'])
def test_repository_regex_replacement_has_no_standard_library_authority(path):
    ir, _, _ = run(sources={path: b'def split(pattern, value):\n    return ["0"]\n'})
    assert not projected(ir)


@pytest.mark.parametrize('source', [
    PRODUCTION.replace('import re', 'import other as re'),
    PRODUCTION.replace('parts = re.split', 're.split = external\n    parts = re.split'),
    PRODUCTION.replace('return [int(p) for p in parts if p]', 'from tests.test_values import expected_output\n    return expected_output.__wrapped__()'),
    PRODUCTION.replace('r"[,\\s]+"', 'pattern'),
])
def test_unknown_regex_source_and_fixture_backlinks_withhold_purity(source):
    ir, _, _ = run(sources={'app/parse_ints.py': source.encode()})
    assert not projected(ir)
