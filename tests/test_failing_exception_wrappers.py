"""A handler that unconditionally fails keeps the checked answer visible."""
import pytest

from checkwash.frontends.python import table_oracles
from test_issue_expectation_families import run

PRODUCTION = 'def first_n_chars(s, n):\n    return s[:n-1]\n'
BEFORE = '''from app.prod import first_n_chars
def test_five_chars():
    assert first_n_chars("hello world", 5) == "hello"
'''
AFTER = '''import pytest
from app.prod import first_n_chars
@pytest.mark.parametrize("text, n, expected", [("hello world", 5, "hell"), ("abc", 2, "a")])
def test_first_n_chars(text, n, expected):
    try:
        result = first_n_chars(text, n)
        assert result == expected
    except Exception as e:
        pytest.fail(f"Unexpected exception: {e}")
'''


def projected(source):
    result = table_oracles._module(source.encode(), baseline=False)
    return result is not None and any(form == 'failing-exception-wrapper' for _, form in result[6])


@pytest.mark.parametrize('after', [
    AFTER, AFTER.replace(' as e:', ' as error:').replace('{e}', '{error}'),
    AFTER.replace('f"Unexpected exception: {e}"', '"unexpected failure"'),
    AFTER.replace('        result = first_n_chars(text, n)\n        assert result == expected',
                  '        assert first_n_chars(text, n) == expected'),
])
def test_parameter_answer_changes_cannot_hide_in_a_failing_handler(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(after)
    assert result[2] == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in result[1])


def test_transparent_failing_handler_preserves_original_answers():
    honest = AFTER.replace('5, "hell"', '5, "hello"').replace('2, "a"', '2, "ab"')
    for source in [PRODUCTION, PRODUCTION.replace('n-1', 'n')]:
        assert run(BEFORE, honest, source)[2] == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('pytest.fail(f"Unexpected exception: {e}")', 'pass'),
    AFTER.replace('pytest.fail(f"Unexpected exception: {e}")', 'return'),
    AFTER.replace('pytest.fail(', 'pytest.skip('),
    AFTER.replace('pytest.fail(', 'recover('),
    AFTER.replace('pytest.fail(', 'pytest.xfail('),
    AFTER.replace('pytest.fail(', 'fail('),
    AFTER.replace('f"Unexpected exception: {e}"', 'format_error(e)'),
    AFTER.replace('f"Unexpected exception: {e}"', 'f"{e!r}"'),
    AFTER.replace('f"Unexpected exception: {e}"', 'f"{e:format}"'),
    AFTER.replace('f"Unexpected exception: {e}"', 'f"{callback()}"'),
    AFTER.replace('f"Unexpected exception: {e}"', '"bad", pytrace=False'),
    AFTER.replace('except Exception as e:', 'except BaseException as e:'),
    AFTER.replace('except Exception as e:', 'except AssertionError as e:'),
    AFTER.replace('except Exception as e:', 'except Exception:'),
    AFTER.replace('except Exception as e:', 'except Exception as pytest:'),
    AFTER.replace('except Exception as e:', 'except Exception as Exception:'),
    AFTER.replace(' as e:', ' as first_n_chars:').replace('{e}', '{first_n_chars}'),
    AFTER.replace(' as e:', ' as text:').replace('{e}', '{text}'),
    AFTER.replace(' as e:', ' as expected:').replace('{e}', '{expected}'),
    AFTER.replace(' as e:', ' as result:').replace('{e}', '{result}'),
    AFTER + '    else:\n        pass\n',
    AFTER + '    finally:\n        pass\n',
    AFTER + '    except ValueError:\n        pass\n',
    AFTER.replace('    try:', '    mutate()\n    try:'),
    AFTER.replace('        result =', '        mutate()\n        result ='),
    AFTER.replace('        pytest.fail', '        mutate()\n        pytest.fail'),
    AFTER.replace('text, n, expected):', 'text, n, expected, Exception):'),
    AFTER.replace('import pytest', 'import pytest as other'),
    AFTER.replace('import pytest', 'from other import pytest'),
    AFTER.replace('from app.prod import', 'from other import Exception\nfrom app.prod import'),
    AFTER + '\nException = ValueError\n',
    AFTER + '\npytest.fail = lambda *args: None\n',
])
def test_unproven_catchers_and_diagnostics_do_not_receive_projection(after):
    assert not projected(after)


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''},
    {'tests/sitecustomize.py': b'import builtins\nbuiltins.Exception = BaseException\n'},
    {'tests/conftest.py': b'import pytest\npytest.fail = lambda *args: None\n'},
    {'tests/test_other.py': b'import pytest\npytest.fail = lambda *args: None\n'},
])
def test_framework_and_startup_authority_must_hold(context):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, AFTER, PRODUCTION, context=context)[1])


@pytest.mark.parametrize('production', [
    'import pytest\npytest.fail = lambda *args: None\n' + PRODUCTION,
    PRODUCTION.replace('    return', '    mutate()\n    return'),
    'from tests.test_case import test_first_n_chars\n' + PRODUCTION,
])
def test_full_production_must_be_inert(production):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, AFTER, production)[1])


def test_same_input_prefix_remains_required():
    after = AFTER.replace('"hello world", 5', '"hello world", 4')
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, after, PRODUCTION)[1])
