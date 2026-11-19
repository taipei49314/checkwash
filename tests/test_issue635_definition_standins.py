"""Issue #635: a definition that takes over an imported subject's name is a stand-in.

`total = lambda lines: 105.0` after `from app.prod import total` is
TEST_PATCHES_SUBJECT (THREATMODEL row 90, #88). The same swap written as a
definition passed 0.13.0 with zero findings: a module-level `def`, a `def`
inside the test, a class, with the import kept or deleted. Production stays
buggy and the assertion stays byte-identical; the test calls the local name.

The trace now treats a `def` or `class` that rebinds a captured import as it
treats the assignment. It does so in the module body and in the observed
test's own body only. A method binds a class attribute, and a definition
inside a fixture or a helper is local to it: the fixture and parameter
implementation passes judge those, and this rule adds no second event there.
"""
import pytest

from checkwash.frontends.python.standin_installations import _definition_rebind
from test_issue_expectation_families import run

PRODUCTION = "def total(lines):\n    return sum(p * q for p, q in lines)\n"
IMPORT = "from app.prod import total\n"
TEST = "def test_total():\n    assert total([(100, 1)]) == 105.0\n"
BEFORE = IMPORT + "\n\n" + TEST
DEF = "def total(lines):\n    return 105.0\n"
MESSAGE = "test_total: this test installs a replacement for app.prod.total that its existing oracle consumes"

POSITIVES = {
    "module_level_def": (IMPORT + "\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "def_inside_the_test": (
        IMPORT + "\n\ndef test_total():\n    def total(lines):\n        return 105.0\n\n"
        "    assert total([(100, 1)]) == 105.0\n", "def total(lines):"),
    "module_level_class": (
        IMPORT + "\n\nclass total(float):\n    def __new__(cls, lines):\n"
        "        return float.__new__(cls, 105.0)\n\n\n" + TEST, "class total(float):"),
    "import_deleted": (DEF + "\n\n" + TEST, "def total(lines):"),
    "decorated_def": (
        IMPORT + "\n\ndef unchanged(function):\n    return function\n\n\n@unchanged\n" + DEF + "\n\n" + TEST,
        "def total(lines):"),
    "async_def": (
        IMPORT + "\n\nasync def total(lines):\n    return 105.0\n\n\n" + TEST, "async def total(lines):"),
    "def_under_a_literal_branch": (
        IMPORT + "\n\nif True:\n    def total(lines):\n        return 105.0\n\n\n" + TEST, "def total(lines):"),
}


def judged(before, after, production=PRODUCTION):
    ir, findings, verdict = run(before, after, production)
    standins = [(f.rule, f.severity, f.unit, f.message) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    return verdict, standins, ir.globals.subject_installations


@pytest.mark.parametrize("name", sorted(POSITIVES))
def test_a_definition_that_takes_over_the_imported_subject_blocks(name):
    after, header = POSITIVES[name]
    verdict, standins, events = judged(BEFORE, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(path, unit, target, text) for path, unit, target, text, _span in events] == [
        ("tests/test_case.py", "test_total", "app.prod.total", header)]


def test_the_assignment_spelling_reports_the_same_finding():
    verdict, standins, _events = judged(BEFORE, IMPORT + "\ntotal = lambda lines: 105.0\n\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_an_edited_local_definition_is_a_new_effect_like_an_edited_lambda():
    before = IMPORT + "\n\ndef total(lines):\n    return sum(p * q for p, q in lines) * 1.05\n\n\n" + TEST
    verdict, standins, _events = judged(before, IMPORT + "\n\n" + DEF + "\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


NEGATIVES = {
    # The same local definition on both sides installs nothing new.
    "definition_unchanged": (
        IMPORT + "\n\n" + DEF + "\n\n" + TEST,
        IMPORT + "\n\n" + DEF + "\n\n" + TEST + "\n\ndef test_other():\n    assert 1 + 1 == 2\n"),
    # Faking the standard library is hygiene, as it is for the assignment.
    "standard_library_name": (
        "from os.path import join\n" + IMPORT + "\n\ndef test_join():\n    assert join('a', 'b')\n\n\n" + TEST,
        "from os.path import join\n" + IMPORT + "\n\ndef join(a, b):\n    return a + '/' + b\n\n\n"
        "def test_join():\n    assert join('a', 'b')\n\n\n" + TEST),
    # A method binds a class attribute; the test still reads the import.
    "method_with_the_name": (
        IMPORT + "\n\nclass TestTotals:\n    def test_total(self):\n        assert total([(100, 1)]) == 105.0\n",
        IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 'label'\n\n"
        "    def test_total(self):\n        assert total([(100, 1)]) == 105.0\n"),
    "another_name": (
        BEFORE,
        IMPORT + "\n\ndef rows():\n    return [(100, 1)]\n\n\ndef test_total():\n    assert total(rows()) == 105.0\n"),
    # Local to a helper the test does not call for its subject.
    "definition_inside_a_helper": (
        BEFORE,
        IMPORT + "\n\ndef label():\n    def total(lines):\n        return 'label'\n    return total\n\n\n" + TEST),
}


@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_a_definition_that_does_not_take_over_the_subject_reports_nothing(name):
    before, after = NEGATIVES[name]
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


def test_a_definition_inside_a_fixture_stays_with_the_fixture_pass():
    """One event, the fixture pass's, where the inner def shares the import's name."""
    before = ("from app.prod import square\ndef test_square():\n"
              "    checks = (square(i) == i * i for i in range(2, 5))\n    assert all(checks)\n")
    after = ("import pytest\nfrom app.prod import square\n@pytest.fixture\ndef correct_square():\n"
             "    def square(x):\n        return x * x\n    return square\n"
             "@pytest.mark.parametrize(\"x, expected\", [(2, 4), (3, 9), (4, 16)])\n"
             "def test_square(correct_square, x, expected):\n    assert correct_square(x) == expected\n")
    _verdict, standins, events = judged(before, after, "def square(x):\n    return x * 2\n")
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_square")]
    assert [event[3] for event in events] == ["assert correct_square(x) == expected"]


@pytest.mark.parametrize("before,after,expected", [
    (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + TEST, True),
    (BEFORE, DEF + "\n\n" + TEST, True),                                   # the import is on the before side only
    (BEFORE, IMPORT + "\n\nclass total:\n    pass\n\n\n" + TEST, True),
    (BEFORE, IMPORT + "\n\ntry:\n    pass\nexcept Exception:\n    def total(lines):\n        return 0\n\n\n" + TEST, True),
    (IMPORT + "\n\n" + DEF + "\n\n" + TEST, IMPORT + "\n\n" + DEF + "\n\n" + TEST + "\n\nX = 1\n", False),
    (BEFORE, IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 0\n\n\n" + TEST, False),
    (BEFORE, IMPORT + "\n\ndef rows():\n    return []\n\n\n" + TEST, False),
    (BEFORE, "def broken(:\n", False),
])
def test_the_scheduling_filter_sees_only_definitions_of_imported_names(before, after, expected):
    assert _definition_rebind(before.encode(), after.encode()) is expected
