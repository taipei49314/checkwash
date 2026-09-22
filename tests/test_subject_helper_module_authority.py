"""Unknown module execution cannot establish an assertion helper's identity."""

import pytest

from test_issue132_subject_replacements import judge, PREFIX


BEFORE = (PREFIX + "def oracle():\n    assert total([1,2]) == 3\n"
          "def other():\n    assert total([1,2]) == 3\ndef test_total():\n    oracle()\n")
AFTER = BEFORE.replace("def oracle():", "def standin(values):\n    return sum(values)\ndef oracle():").replace(
    "assert total([1,2]) == 3\ndef other", "assert standin([1,2]) == 3\ndef other")


@pytest.mark.parametrize("executed", [
    "globals()['oracle'] = other", "locals()['oracle'] = other", "vars()['oracle'] = other",
    "setattr(oracle, '__code__', other.__code__)", "oracle.__code__ = other.__code__",
    "oracle.__dict__['dispatch'] = other", "exec('oracle = other')", "mutate()",
    "@mutate\ndef unrelated():\n    pass", "def unrelated(value=mutate()):\n    pass",
    "def unrelated(value: mutate()):\n    pass", "def unrelated() -> mutate():\n    pass",
    "if enabled:\n    oracle = other", "import late_mutator", "oracle = other",
    "def setup_function():\n    mutate()",
])
def test_unknown_module_execution_withholds_helper_namespace(executed):
    findings = judge(BEFORE + executed + "\n", AFTER + executed + "\n")
    assert not any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)


def test_stable_literal_constant_and_alias_keep_closed_helper_proof():
    common = "VALUE = 3\noriginal = total\n"
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in judge(
        BEFORE.replace("def oracle():", common + "def oracle():"), AFTER.replace("def oracle():", common + "def oracle():")))


def test_rebound_unused_helper_has_unchanged_live_production_behavior():
    suffix = "globals()['oracle'] = other\n"
    observations = []
    for source in (BEFORE + suffix, AFTER + suffix):
        seen = []
        namespace = {"total": lambda values: seen.append(tuple(values)) or sum(values)}
        exec(source.removeprefix(PREFIX), namespace)
        namespace["test_total"]()
        observations.append(seen)
    assert observations == [[(1, 2)], [(1, 2)]]
    assert not any(f.rule == "TEST_PATCHES_SUBJECT" for f in judge(BEFORE + suffix, AFTER + suffix))
