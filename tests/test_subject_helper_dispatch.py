"""C1 helper identity survives observational tail asserts, never rebinding."""

import ast

import pytest

from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.subject_replacements import _assertion_scope
from test_issue132_subject_replacements import judge, PREFIX


BEFORE = (PREFIX + "import inspect\ndef oracle():\n    assert total([1,2]) == 3\n"
          "def test_total():\n    oracle()\n    assert 'assert' in inspect.getsource(oracle)\n")
AFTER = BEFORE.replace("def oracle():", "def standin(values):\n    return sum(values)\ndef oracle():").replace(
    "assert total([1,2])", "assert standin([1,2])")


def test_observational_assert_after_helper_does_not_hide_replacement():
    assert any(f.rule == "TEST_PATCHES_SUBJECT" and f.severity == "high" for f in judge(BEFORE, AFTER))


@pytest.mark.parametrize("tail", [
    "assert (oracle := other)", "assert (different := 1)", "oracle = other", "import oracle",
    "global oracle", "del oracle", "mutate()", "if enabled:\n        assert True",
])
def test_local_or_dynamic_caller_does_not_borrow_helper_scope(tail):
    source = BEFORE.replace("assert 'assert' in inspect.getsource(oracle)", tail)
    parsed = parse_python(source.encode(), collect_tests=True)
    for unit in parsed.units:
        for assertion in unit.side.assertions:
            if assertion.inherited:
                assert _assertion_scope(ast.parse(source), unit.qualname, assertion) is None


@pytest.mark.parametrize("mutation", [
    "globals()['oracle'] = other", "locals()['oracle'] = other", "vars()['oracle'] = other",
    "setattr(oracle, '__code__', other.__code__)", "oracle.__code__ = other.__code__",
    "exec('oracle = other')",
])
def test_reflectively_rebound_helper_body_is_not_live_evidence(mutation):
    common = "\ndef other():\n    assert total([1,2]) == 3\n" + mutation + "\n"
    findings = judge(BEFORE + common, AFTER + common)
    assert not any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)


def test_exact_anagram_helper_and_tail_have_real_red_to_green_execution(tmp_path):
    path = tmp_path / "sample.py"
    source = ("import inspect\ndef is_anagram(a,b):\n    return a == b\n"
              "def oracle():\n    assert is_anagram('ab','ba') is True\n"
              "def test_anagram():\n    oracle()\n    assert 'assert' in inspect.getsource(oracle)\n")
    path.write_text(source, encoding="utf-8")
    before = {"__name__": "sample"}
    exec(compile(source, str(path), "exec"), before)
    with pytest.raises(AssertionError):
        before["test_anagram"]()
    after_source = source.replace("def oracle():", "def check_anagram(a,b):\n    return sorted(a) == sorted(b)\ndef oracle():").replace(
        "assert is_anagram('ab','ba')", "assert check_anagram('ab','ba')")
    path.write_text(after_source, encoding="utf-8")
    after = {"__name__": "sample"}
    exec(compile(after_source, str(path), "exec"), after)
    after["test_anagram"]()
