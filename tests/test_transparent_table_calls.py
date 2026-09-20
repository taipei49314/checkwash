"""Concrete table cases retain transparent production forwarding (#130)."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


def run(before, after, production, *, context=None):
    path = "tests/test_cases.py"
    snapshot = {"src/app/__init__.py": b"", "src/app/prod.py": production.encode(), path: after.encode()}
    snapshot.update(context or {})
    return analyze([FileChange(path=path, status="modified", before=before.encode(), after=after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   known_modules={"app", "pytest"}, self_modules={"app"}, head_reader=snapshot.get,
                   head_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


BEFORE = ("from app.prod import abs_diff\ndef test_negative_delta():\n    assert abs_diff(3, 10) == 7\n"
          "def test_positive_delta():\n    assert abs_diff(10, 3) == 7\n")
AFTER = ("from app.prod import abs_diff\ndef calculate_abs_diff(a, b):\n    return abs_diff(a, b)\n"
         "def test_abs_diff():\n    cases = [(3, 10, 7), (10, 3, 7), (-5, -15, 10)]\n"
         "    for a, b, expected in cases:\n        assert calculate_abs_diff(a, b) == expected\n")
PRODUCTION = "def abs_diff(a, b):\n    return abs(a - b)\n"


def test_forwarded_literal_loop_preserves_the_complete_original_prefix():
    assert run(BEFORE, AFTER, PRODUCTION)[2] == "pass"


def test_params_fixture_and_local_forwarded_result_preserve_all_original_cases():
    before = ("from app.prod import fill_none\ndef test_middle():\n    assert fill_none([1, None, 2], 0) == [1, 0, 2]\n"
              "def test_only_none():\n    assert fill_none([None], 0) == [0]\n"
              "def test_keeps_zero():\n    assert fill_none([0, 1], 9) == [0, 1]\n")
    after = ("import pytest\nfrom app.prod import fill_none\n"
             "@pytest.fixture(params=[([1, None, 2], 0, [1, 0, 2]), ([None], 0, [0]), ([0, 1], 9, [0, 1])])\n"
             "def test_data(request):\n    return request.param\n"
             "def apply_fill_none(xs, default):\n    return fill_none(xs, default)\n"
             "def test_fill_none(test_data):\n    xs, default, expected = test_data\n"
             "    result = apply_fill_none(xs, default)\n    assert result == expected\n")
    prod = "def fill_none(xs, default):\n    return [default if x is None else x for x in xs]\n"
    assert run(before, after, prod)[2] == "pass"
    changed = after.replace("([None], 0, [0])", "([None], 0, [None])")
    assert run(before, changed, prod)[2] == "block"


@pytest.mark.parametrize("replacement", [
    "return 7", "return abs_diff(a, b) + 1", "return abs_diff(a, a)",
    "return abs_diff(b, a)", "return abs_diff(a, b) if a > b else 7",
])
def test_changed_forwarder_cannot_supply_unchanged_call_evidence(replacement):
    assert run(BEFORE, AFTER.replace("return abs_diff(a, b)", replacement), PRODUCTION)[2] == "block"


def test_forwarded_same_input_expected_rewrite_still_blocks():
    assert run(BEFORE, AFTER.replace("(3, 10, 7)", "(3, 10, -7)"), PRODUCTION)[2] == "block"


@pytest.mark.parametrize("extra", [
    "calculate_abs_diff = lambda a, b: 7\n",
    "def calculate_abs_diff(a, b):\n    return 7\n",
])
def test_module_forwarder_rebinding_withholds_projection(extra):
    after = AFTER.replace("def test_abs_diff", extra + "def test_abs_diff")
    assert run(BEFORE, after, PRODUCTION)[2] == "block"


def test_unknown_fixture_startup_withholds_forwarding_credit():
    assert run(BEFORE, AFTER, PRODUCTION, context={"conftest.py": b"def pytest_sessionstart(session):\n    configure()\n"})[2] == "block"


@pytest.mark.parametrize("production", [
    "from tests.test_cases import calculate_abs_diff\ndef abs_diff(a,b):\n    return calculate_abs_diff(a,b)\n",
    "def abs_diff(a,b):\n    from tests.test_cases import calculate_abs_diff\n    return calculate_abs_diff(a,b)\n",
    "def abs_diff(a,b):\n    return getattr(__import__('tests.test_cases'), 'calculate_abs_diff')(a,b)\n",
])
def test_production_backreference_withholds_transparent_forwarding_credit(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("import_line", ["import mutator\n", "from mutator import unused\n"])
def test_uninspected_import_cannot_override_proved_production(import_line):
    ir, _, _ = run(import_line + BEFORE, import_line + AFTER, PRODUCTION,
                   context={"mutator.py": b"from app.prod import abs_diff\nabs_diff.__code__ = replacement.__code__\n"})
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


STRIP_BEFORE = ("from app.prod import strip_prefix\ndef test_hit():\n    assert strip_prefix('foobar', 'foo') == 'bar'\n"
                "def test_miss():\n    assert strip_prefix('foobar', 'baz') == 'foobar'\n"
                "def test_empty_prefix():\n    assert strip_prefix('ab', '') == 'ab'\n")
STRIP_AFTER = ("from app.prod import strip_prefix\ndef strip_prefix_helper(s, prefix, expected):\n"
               "    result = strip_prefix(s, prefix)\n"
               "    assert result == expected, f'Expected {expected}, but got {result}'\n"
               "def test_strip_prefix():\n    test_cases = [('foobar', 'foo', 'bar'), ('foobar', 'baz', 'foobar'), ('ab', '', 'ab')]\n"
               "    for s, prefix, expected in test_cases:\n        strip_prefix_helper(s, prefix, expected)\n")
STRIP_PROD = "def strip_prefix(s, prefix):\n    if s.startswith(prefix):\n        return s[len(prefix):]\n    return s\n"


def test_literal_string_helper_message_keeps_historical_strip_prefix_cases():
    assert run(STRIP_BEFORE, STRIP_AFTER, STRIP_PROD)[2] == "pass"


@pytest.mark.parametrize("expected", ["'bar!'", "'foobar'"])
def test_helper_diagnostic_cannot_hide_a_rewritten_expected_value(expected):
    after = STRIP_AFTER.replace("('foobar', 'foo', 'bar')", f"('foobar', 'foo', {expected})")
    assert run(STRIP_BEFORE, after, STRIP_PROD)[2] == "block"


@pytest.mark.parametrize("production", [
    "def strip_prefix(s, prefix):\n    return unknown_result()\n",
    "class Result:\n    def __format__(self, spec):\n        terminate_suite()\ndef strip_prefix(s, prefix):\n    return Result()\n",
    "def strip_prefix(s, prefix):\n    change_runtime()\n    return s\n",
])
def test_unknown_or_effectful_production_result_cannot_gain_message_credit(production):
    assert run(STRIP_BEFORE, STRIP_AFTER, production)[2] == "block"


@pytest.mark.parametrize("message", ["terminate_suite()", "f'{result.custom}'", "f'{result:{dynamic_format}}'", "f'{replace(expected)}'"])
def test_unknown_assertion_message_does_not_gain_concrete_oracle_credit(message):
    after = STRIP_AFTER.replace("f'Expected {expected}, but got {result}'", message)
    assert run(STRIP_BEFORE, after, STRIP_PROD)[2] == "block"


def test_unused_import_with_runtime_effects_withholds_message_proof():
    before = "import mutator\n" + STRIP_BEFORE
    after = "import mutator\n" + STRIP_AFTER
    assert run(before, after, STRIP_PROD, context={"mutator.py": b"change_runtime()\n"})[2] == "block"


SLUG_BEFORE = ("import pytest\nfrom app.prod import slugify\n@pytest.fixture\ndef slugged():\n"
               "    assert slugify('Hello World') == 'hello-world'\n    return slugify\n"
               "def test_punctuation(slugged):\n    assert slugged('Hello, World!') == 'hello-world'\n")
SLUG_AFTER = ("import pytest\nfrom app.prod import slugify\n@pytest.fixture\ndef input_strings():\n"
              "    return ['Hello World', 'Hello, World!']\n"
              "def test_slugify(input_strings):\n    expected = ['hello-world', 'hello-world']\n"
              "    for s, expected_slug in zip(input_strings, expected):\n        assert slugify(s) == expected_slug\n")
SLUG_PROD = ("import re\ndef slugify(s):\n    s = s.lower().strip()\n"
             "    s = re.sub(r'[^a-z0-9]+', '-', s)\n    return s.strip('-')\n")


def test_callable_fixture_assertion_and_returned_alias_survive_literal_zip_consolidation():
    result = run(SLUG_BEFORE, SLUG_AFTER, SLUG_PROD)
    assert result[2] == "pass"
    units = result[0].files[0].units
    assert len(units) == 2
    assert all(unit.before and unit.after for unit in units)
    assert {unit.after.assertions[0].left for unit in units} == {"slugify('Hello World')", "slugify('Hello, World!')"}
    assert all(unit.before.assertions[0].left == unit.after.assertions[0].left for unit in units)


@pytest.mark.parametrize("old,new", [
    ("['hello-world', 'hello-world']", "['Hello-World', 'hello-world']"),
    ("['hello-world', 'hello-world']", "['hello-world']"),
    ("['Hello World', 'Hello, World!']", "['Hello, World!']"),
    ("zip(input_strings, expected)", "zip(expected, input_strings)"),
    ("zip(input_strings, expected)", "zip(input_strings, expected, strict=False)"),
    ("return ['Hello World', 'Hello, World!']", "return get_inputs()"),
])
def test_zip_consolidation_does_not_hide_answers_or_disappeared_fixture_assertions(old, new):
    assert run(SLUG_BEFORE, SLUG_AFTER.replace(old, new), SLUG_PROD)[2] == "block"


@pytest.mark.parametrize("definition", [
    "@pytest.fixture(scope='module')", "@pytest.fixture(autouse=True)",
])
def test_unknown_fixture_execution_semantics_do_not_gain_callable_prefix_credit(definition):
    before = SLUG_BEFORE.replace("@pytest.fixture", definition)
    assert run(before, SLUG_AFTER, SLUG_PROD)[2] == "block"


def test_fixture_return_yield_and_extra_effects_remain_unproved():
    before = SLUG_BEFORE.replace("    return slugify", "    change_runtime()\n    return slugify")
    assert run(before, SLUG_AFTER, SLUG_PROD)[2] == "block"


@pytest.mark.parametrize("shadow", ["zip = 1\n", "zip = custom_zip\n"])
def test_rebound_zip_cannot_authorize_literal_rows(shadow):
    after = SLUG_AFTER.replace("@pytest.fixture", shadow + "@pytest.fixture")
    assert run(SLUG_BEFORE, after, SLUG_PROD)[2] == "block"


@pytest.mark.parametrize("context", [
    {"re.py": b"def sub(pattern, replacement, value):\n    change_runtime()\n    return value\n"},
    {"conftest.py": b"def pytest_sessionstart(session):\n    configure_runtime()\n"},
])
def test_zip_requires_closed_source_and_standard_regex_authority(context):
    assert run(SLUG_BEFORE, SLUG_AFTER, SLUG_PROD, context=context)[2] == "block"


def test_effectful_source_cannot_prove_builtin_zip_is_stable():
    production = SLUG_PROD.replace("    s = s.lower().strip()", "    poison_zip()\n    s = s.lower().strip()")
    assert run(SLUG_BEFORE, SLUG_AFTER, production)[2] == "block"
