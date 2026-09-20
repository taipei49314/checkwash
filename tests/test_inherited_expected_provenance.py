"""Expectation evidence follows the concrete collected inherited consumer."""

import pytest

from test_issue_expectation_families import run


BEFORE = """from app.prod import identity
class Checks:
    def test_value(self):
        assert identity(3) == 3
class TestId(Checks):
    pass
class TestDummy:
    def test_ok(self):
        assert True
"""
HELPER = "def expected_value(x):\n    return x + 1\n"


@pytest.mark.parametrize("carrier", [
    "assert identity(3) == expected_value(3)",
    "expected = expected_value(3)\n        assert identity(3) == expected",
    "assert expected_value(3) == identity(3)",
])
@pytest.mark.parametrize("descendants", [
    "class TestId(Checks):\n    pass",
    "class Middle(Checks):\n    pass\nclass TestId(Middle):\n    pass",
    "class TestId(Checks):\n    pass\nclass TestOther(Checks):\n    pass",
])
def test_expected_helper_replacement_is_owned_by_collected_descendants(carrier, descendants):
    before = BEFORE.replace("class TestId(Checks):\n    pass", descendants)
    after = HELPER + before.replace("assert identity(3) == 3", carrier)
    ir, findings, verdict = run(before, after, "def identity(x):\n    return x + 1\n")
    expected = {"TestId.test_value"}
    if "TestOther" in descendants:
        expected.add("TestOther.test_value")
    observed = {finding.unit for finding in findings
                if finding.rule == "EXPECTATION_DEFINITION_CHANGED"}
    assert expected <= observed
    assert verdict == "block"


@pytest.mark.parametrize("shadow", [
    "    test_value = None",
    "    def test_value(self):\n        assert True",
    "    __test__ = False",
])
def test_shadowed_inherited_oracle_has_no_provenance_owner(shadow):
    before = BEFORE.replace("class TestId(Checks):\n    pass", "class TestId(Checks):\n" + shadow)
    after = HELPER + before.replace("assert identity(3) == 3", "assert identity(3) == expected_value(3)")
    _, findings, _ = run(before, after, "def identity(x):\n    return x + 1\n")
    assert not [finding for finding in findings if finding.rule == "EXPECTATION_DEFINITION_CHANGED"]


@pytest.mark.parametrize("change", [
    "# unchanged oracle\n",
    "def unused_expected_value(x):\n    return x + 1\n",
])
def test_inherited_oracle_unchanged_by_unconsumed_source(change):
    assert run(BEFORE, change + BEFORE, "def identity(x):\n    return x\n")[2] == "pass"


def test_inherited_unchanged_helper_does_not_create_an_event():
    before = HELPER + BEFORE.replace("assert identity(3) == 3", "assert identity(3) == expected_value(3)")
    assert run(before, "# comment\n" + before, "def identity(x):\n    return x + 1\n")[2] == "pass"
