"""Issue #635: a definition that takes over an imported subject's name is a stand-in.

`total = lambda lines: 105.0` after `from app.prod import total` is
TEST_PATCHES_SUBJECT (THREATMODEL row 90, #88). The same swap written as a
definition passed 0.13.0 with zero findings: a `def` or a class of the name,
with the import kept or deleted. Production stays buggy and the assertion
stays byte-identical; the test calls the local name.

The trace now treats a `def` or `class` that rebinds a captured import as it
treats the assignment, wherever it reads assignments: the module body and the
bodies of the functions it follows (the test and the helpers it calls), in a
test file or a conftest, as a direct statement or under `with` or a literal
`if`. A method binds a class attribute and a pytest fixture binds a fixture;
neither takes over a name a test calls.

Not read, for the assignment as for the definition: a statement under `try`,
a loop, `match` or an `if` whose test is not a literal. Not read for the
definition only: the body of a pytest fixture, which the fixture passes judge.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.standin_installations import _definition_rebind
from checkwash.gitio.snapshot import search_source_mapping
from test_issue_expectation_families import run

PRODUCTION = "def total(lines):\n    return sum(p * q for p, q in lines)\n"
IMPORT = "from app.prod import total\n"
TEST = "def test_total():\n    assert total([(100, 1)]) == 105.0\n"
BEFORE = IMPORT + "\n\n" + TEST
DEF = "def total(lines):\n    return 105.0\n"
CLASS = "class total(float):\n    def __new__(cls, lines):\n        return float.__new__(cls, 105.0)\n"
MESSAGE = "test_total: this test installs a replacement for app.prod.total that its existing oracle consumes"
HELPER_BEFORE = IMPORT + "\n\ndef computed():\n    return total([(100, 1)])\n\n\ndef test_total():\n    assert computed() == 105.0\n"
FIXTURE_BEFORE = ("import pytest\n" + IMPORT + "\n\n@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n\n\n"
                  "def test_total(amount):\n    assert amount == 105.0\n")
ALIAS = "from app import prod\n\ntotal = prod.total\n\n\n"

# name -> (before, after, the evidence line)
POSITIVES = {
    "module_level_def": (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "def_inside_the_test": (
        BEFORE,
        IMPORT + "\n\ndef test_total():\n    def total(lines):\n        return 105.0\n\n"
        "    assert total([(100, 1)]) == 105.0\n", "def total(lines):"),
    "module_level_class": (BEFORE, IMPORT + "\n\n" + CLASS + "\n\n" + TEST, "class total(float):"),
    "import_deleted": (BEFORE, DEF + "\n\n" + TEST, "def total(lines):"),
    "decorated_def": (
        BEFORE,
        IMPORT + "\n\ndef unchanged(function):\n    return function\n\n\n@unchanged\n" + DEF + "\n\n" + TEST,
        "def total(lines):"),
    # Still a takeover, although pytest stays red here: the coroutine is not 105.0.
    "async_def": (BEFORE, IMPORT + "\n\nasync def total(lines):\n    return 105.0\n\n\n" + TEST, "async def total(lines):"),
    "def_under_a_literal_branch": (
        BEFORE, IMPORT + "\n\nif True:\n    def total(lines):\n        return 105.0\n\n\n" + TEST, "def total(lines):"),
    "def_under_with": (
        BEFORE,
        "import contextlib\n" + IMPORT + "\n\nwith contextlib.suppress(KeyError):\n"
        "    def total(lines):\n        return 105.0\n\n\n" + TEST, "def total(lines):"),
    # A second definition of the name still replaces the import (the last one is the evidence).
    "def_written_twice": (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "another_def_then_the_def": (
        BEFORE,
        IMPORT + "\n\ndef total(lines):\n    return 0.0\n\n\ndef total(rows):\n    return 105.0\n\n\n" + TEST,
        "def total(rows):"),
    "class_then_def": (BEFORE, IMPORT + "\n\nclass total:\n    pass\n\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "def_then_class": (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + CLASS + "\n\n" + TEST, "class total(float):"),
    "def_then_lambda": (
        BEFORE, IMPORT + "\n\n" + DEF + "\n\ntotal = lambda lines: 105.0\n\n\n" + TEST, "total = lambda lines: 105.0"),
    # A standard-library import of the name in front of the definition is no cover.
    "decoy_import_then_def": (
        BEFORE, IMPORT + "from os.path import join as total\n\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    # The name was captured by an assignment, not by an import statement.
    "alias_then_def": (ALIAS + TEST, ALIAS + DEF + "\n\n" + TEST, "def total(lines):"),
    # Where the assignment spelling is read, the definition is too.
    "def_in_a_helper_the_test_asserts_through": (
        HELPER_BEFORE,
        IMPORT + "\n\ndef computed():\n    def total(lines):\n        return 105.0\n\n"
        "    return total([(100, 1)])\n\n\ndef test_total():\n    assert computed() == 105.0\n", "def total(lines):"),
    # A decorator that is only called `fixture` does not make the definition a fixture.
    "decoy_fixture_decorator": (
        BEFORE,
        IMPORT + "\n\ndef fixture(function):\n    return function\n\n\n@fixture\n" + DEF + "\n\n" + TEST,
        "def total(lines):"),
    "patched_fixture_decorator": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\npytest.fixture = lambda function: function\n\n\n@pytest.fixture\n"
        + DEF + "\n\n" + TEST, "def total(lines):"),
    # An optional import of anything but the replaced provider cannot restore production.
    "def_then_optional_import_of_another_module": (
        BEFORE, IMPORT + "\n\n" + DEF + "\n\ntry:\n    from app.fast import total\nexcept ImportError:\n    pass\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_optional_import_of_a_standard_library_name": (
        BEFORE, DEF + "\n\ntry:\n    from math import fsum as total\nexcept ImportError:\n    pass\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_unknown_branch_importing_another_module": (
        BEFORE, "import sys\n" + IMPORT + "\n\n" + DEF + "\n\nif sys.platform == 'plan9':\n    from app.fast import total\n\n\n" + TEST,
        "def total(lines):"),
    # The definition was already in the file, where it did not bind the name the test reads.
    "import_moved_above_the_def": (DEF + "\n\n" + IMPORT + "\n\n" + TEST, IMPORT + "\n\n" + DEF + "\n\n" + TEST,
                                   "def total(lines):"),
    "moved_out_of_an_unused_helper": (
        IMPORT + "\n\ndef unused():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n" + TEST,
        IMPORT + "\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "dead_branch_made_live": (
        IMPORT + "\n\nif False:\n    def total(lines):\n        return 105.0\n\n\n" + TEST,
        IMPORT + "\n\nif True:\n    def total(lines):\n        return 105.0\n\n\n" + TEST, "def total(lines):"),
}


def judged(before, after, production=PRODUCTION):
    ir, findings, verdict = run(before, after, production)
    standins = [(f.rule, f.severity, f.unit, f.message) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    return verdict, standins, ir.globals.subject_installations


@pytest.mark.parametrize("name", sorted(POSITIVES))
def test_a_definition_that_takes_over_the_imported_subject_blocks(name):
    before, after, evidence = POSITIVES[name]
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(path, unit, target, text) for path, unit, target, text, _span in events] == [
        ("tests/test_case.py", "test_total", "app.prod.total", evidence)]


def test_the_assignment_spelling_reports_the_same_finding():
    verdict, standins, _events = judged(BEFORE, IMPORT + "\ntotal = lambda lines: 105.0\n\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_an_edited_local_definition_is_a_new_effect_like_an_edited_lambda():
    before = IMPORT + "\n\ndef total(lines):\n    return sum(p * q for p, q in lines) * 1.05\n\n\n" + TEST
    verdict, standins, _events = judged(before, IMPORT + "\n\n" + DEF + "\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_newness_is_per_test_by_what_its_assertions_consume():
    """An unchanged local definition is new for a test that starts to assert through it."""
    before = IMPORT + "\n\n" + DEF + "\n\ndef test_total():\n    assert 1 + 1 == 2\n"
    verdict, standins, _events = judged(before, IMPORT + "\n\n" + DEF + "\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_evidence_text_has_no_carriage_return():
    after = (IMPORT + "\n\n" + DEF + "\n\n" + TEST).replace("\n", "\r\n")
    _verdict, _standins, events = judged(BEFORE.replace("\n", "\r\n"), after)
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


SHADOWED = IMPORT + "\n\n" + DEF + "\n\n" + TEST
NEGATIVES = {
    # The same definition on both sides, consumed by the same test, is nothing
    # new. It moves down two lines, so an identity with positions would differ.
    "definition_unchanged_and_shifted": (
        SHADOWED, IMPORT + "\nROWS = [(100, 1)]\n\n\n" + DEF + "\n\n" + TEST + "\n\ndef test_other():\n    assert ROWS\n"),
    "docstring_added_to_a_shadowing_definition": (
        SHADOWED, IMPORT + "\n\ndef total(lines):\n    \"\"\"The fixed total.\"\"\"\n    return 105.0\n\n\n" + TEST),
    "annotations_added_to_a_shadowing_definition": (
        SHADOWED, IMPORT + "\n\ndef total(lines: list) -> float:\n    return 105.0\n\n\n" + TEST),
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
    # Local to a helper that the test calls for something else.
    "definition_inside_a_helper_called_for_another_value": (
        IMPORT + "\n\ndef rows():\n    return [(100, 1)]\n\n\ndef test_total():\n    assert total(rows()) == 105.0\n",
        IMPORT + "\n\ndef rows():\n    def total(lines):\n        return 'label'\n\n    return [(100, 1)]\n\n\n"
        "def test_total():\n    assert total(rows()) == 105.0\n"),
    # A pytest fixture named like the imported module binds a fixture.
    "fixture_named_like_the_import": (
        "import pytest\nfrom app import prod\n\n\ndef test_total():\n    assert prod.total([(100, 1)]) == 105.0\n",
        "import pytest\nfrom app import prod\n\n\n@pytest.fixture\ndef prod():\n    return [(100, 1)]\n\n\n"
        "def test_total():\n    assert prod.total([(100, 1)]) == 105.0\n"),
    # The same provider's import still wins when it succeeds, so the takeover is not proved.
    "fallback_definition_above_an_optional_import": (
        BEFORE, DEF + "\n\ntry:\n    from app.prod import total\nexcept ImportError:\n    pass\n\n\n" + TEST),
    "fallback_definition_above_a_version_branch_import": (
        BEFORE, "import sys\n\n\n" + DEF + "\n\nif sys.version_info >= (3, 11):\n    from app.prod import total\n\n\n" + TEST),
    # A module-level definition does not take over an import made inside the test.
    "import_inside_the_test": (
        "def test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n",
        DEF + "\n\ndef test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n"),
}


@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_a_definition_that_does_not_take_over_the_subject_reports_nothing(name):
    before, after = NEGATIVES[name]
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


FIXTURE_HEAD = "import pytest\n" + IMPORT + "\n\n@pytest.fixture\ndef amount():\n"
FIXTURE_TAIL = "    return total([(100, 1)])\n\n\ndef test_total(amount):\n    assert amount == 105.0\n"


def test_a_definition_inside_a_fixture_body_stays_with_the_fixture_passes():
    """Known gap, pinned: the assignment in the same place is reported, the definition is not.

    The fixture passes report a local implementation only in the shapes they
    prove (tests/test_generator_fixture_subjects.py pins what they decline).
    """
    _verdict, standins, events = judged(
        FIXTURE_BEFORE, FIXTURE_HEAD + "    def total(lines):\n        return 105.0\n\n" + FIXTURE_TAIL)
    assert standins == [] and events == []
    verdict, standins, _events = judged(FIXTURE_BEFORE, FIXTURE_HEAD + "    total = lambda lines: 105.0\n" + FIXTURE_TAIL)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_definition_in_a_helper_that_a_fixture_calls_stays_with_the_fixture_passes():
    before = (FIXTURE_HEAD.replace("@pytest.fixture", "def computed():\n    return total([(100, 1)])\n\n\n@pytest.fixture")
              + "    return computed()\n\n\ndef test_total(amount):\n    assert amount == 105.0\n")
    after = before.replace("def computed():\n", "def computed():\n    def total(lines):\n        return 105.0\n\n")
    assert after != before
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


def test_a_fixture_whose_decorator_was_replaced_is_followed_like_a_helper():
    """`pytest.fixture` replaced in the file: the "fixture" is a plain function the test calls."""
    head = "import pytest\n" + IMPORT + "\npytest.fixture = lambda function: function\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    return total([(100, 1)])\n\n\ndef test_total():\n    assert amount() == 105.0\n"
    verdict, standins, events = judged(head + tail, head + "    def total(lines):\n        return 105.0\n\n" + tail)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_a_specialised_pass_that_reports_the_same_replacement_keeps_its_evidence():
    """One finding per fingerprint: the fixture pass's, not a second one for the inner def."""
    before = ("from app.prod import square\ndef test_square():\n"
              "    checks = (square(i) == i * i for i in range(2, 5))\n    assert all(checks)\n")
    after = ("import pytest\nfrom app.prod import square\n@pytest.fixture\ndef correct_square():\n"
             "    def square(x):\n        return x * x\n    return square\n"
             "@pytest.mark.parametrize(\"x, expected\", [(2, 4), (3, 9), (4, 16)])\n"
             "def test_square(correct_square, x, expected):\n    assert correct_square(x) == expected\n")
    _verdict, standins, events = judged(before, after, "def square(x):\n    return x * 2\n")
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_square")]
    assert [event[3] for event in events] == ["assert correct_square(x) == expected"]


@pytest.mark.parametrize("carried", ["total = total", "total = staticmethod(total).__func__"])
def test_an_assignment_that_carries_the_definition_on_is_not_a_second_finding(carried):
    after = IMPORT + "\n\n" + DEF + "\n\n" + carried + "\n\n\n" + TEST
    _verdict, standins, events = judged(BEFORE, after)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_a_definition_returned_by_a_helper_and_assigned_keeps_the_released_finding():
    """0.13.0 reports the assignment; the helper's definition is that same stand-in."""
    after = (IMPORT + "\n\ndef subject():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n"
             "def test_total():\n    total = subject()\n    assert total([(100, 1)]) == 105.0\n")
    _verdict, standins, events = judged(BEFORE, after)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["total = subject()"]


def test_two_definitions_that_both_reach_the_assertion_are_one_finding():
    after = (IMPORT + "\n\n" + DEF + "\n\nFIRST = total([(100, 1)])\n\n\n" + DEF + "\n\n"
             "def test_total():\n    assert FIRST == 105.0\n    assert total([(100, 1)]) == 105.0\n")
    before = IMPORT + "\n\nFIRST = total([(100, 1)])\n\n\ndef test_total():\n    assert FIRST == 105.0\n    assert total([(100, 1)]) == 105.0\n"
    _verdict, standins, events = judged(before, after)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert len(events) == 1


def test_a_respelled_call_beside_the_definition_is_one_finding_with_the_released_evidence():
    before = "from app import prod\n\n\ndef test_total():\n    assert prod.total([(100, 1)]) == 105.0\n"
    _verdict, standins, events = judged(before, IMPORT + "\n\n" + DEF + "\n\n" + TEST)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(target, text) for _path, _unit, target, text, _span in events] == [
        ("app.prod.total", "assert total([(100, 1)]) == 105.0")]


MONEY = "class Money:\n    @staticmethod\n    def total(lines):\n        return sum(p * q for p, q in lines)\n"
MONEY_TEST = "def test_total():\n    assert Money.total([(100, 1)]) == 105.0\n"


@pytest.mark.parametrize("install", [
    "Money.total = staticmethod(lambda lines: 105.0)",
    "setattr(Money, 'total', staticmethod(lambda lines: 105.0))",
])
def test_an_attribute_written_on_an_existing_shadow_class_still_names_production(install):
    """0.13.0 reports this; a class that takes over an import must not hide it."""
    shadow = "from app.prod import Money\n\n\nclass Money(Money):\n    pass\n\n\n"
    after = shadow + "def test_total():\n    " + install + "\n    assert Money.total([(100, 1)]) == 105.0\n"
    verdict, standins, events = judged(shadow + MONEY_TEST, after, MONEY)
    assert verdict == "block"
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_total")]
    assert [target for _path, _unit, target, _text, _span in events] == ["app.prod.Money.total"]


def test_a_new_class_keeps_the_released_finding_for_an_attribute_written_on_it():
    """The attribute's finding (0.13.0's fingerprint) stays; the class adds its own."""
    production = "class Config:\n    rate = 0.0\n"
    use = "def test_rate():\n    assert Config.rate == 0.05\n"
    before = "from app.prod import Config\n\n\n" + use
    after = "from app.prod import Config\n\n\nclass Config:\n    pass\n\n\nConfig.rate = 0.05\n\n\n" + use
    verdict, _standins, events = judged(before, after, production)
    assert verdict == "block"
    assert sorted((target, text) for _path, _unit, target, text, _span in events) == [
        ("app.prod.Config", "class Config:"), ("app.prod.Config.rate", "Config.rate = 0.05")]


def test_a_class_that_takes_over_nothing_stays_unbound():
    """A local class with no captured import of its name changes no reading of the name."""
    before = "import app.prod as billing\n\n\ndef test_total():\n    assert billing.total([(100, 1)]) == 105.0\n"
    after = ("import app.prod as billing\n\n\nclass Rows:\n    pass\n\n\n"
             "def test_total():\n    billing.total = lambda lines: 105.0\n    assert billing.total([(100, 1)]) == 105.0\n")
    _verdict, standins, events = judged(before, after)
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_total")]
    assert [target for _path, _unit, target, _text, _span in events] == ["app.prod.total"]


CONFTEST = "import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n"
CONFTEST_TEST = b"def test_total(amount):\n    assert amount == 105.0\n"


def judge_files(before, after, unchanged):
    common = {"app/__init__.py": b"", "app/prod.py": PRODUCTION.encode(), **unchanged}
    changes = [FileChange(path, "modified", before[path].encode(), after[path].encode()) for path in sorted(after)]
    snapshot = {**common, **{path: source.encode() for path, source in after.items()}}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 11, 19),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_path_lister=lambda: sorted(snapshot),
                   root_batch_reader=lambda paths: {path: snapshot.get(path) for path in paths})


def conftest_findings(after):
    _ir, findings, verdict = judge_files({"tests/conftest.py": CONFTEST}, {"tests/conftest.py": after},
                                         {"tests/test_total.py": CONFTEST_TEST})
    return verdict, [(f.rule, f.severity, f.path) for f in findings
                     if f.rule in ("CONFTEST_PATCHES_PROD", "TEST_PATCHES_SUBJECT")]


@pytest.mark.parametrize("install", ["def total(lines):\n    return 105.0\n", "total = lambda lines: 105.0\n"])
def test_a_definition_in_a_conftest_module_body_is_reported_as_the_assignment_is(install):
    after = ("import pytest\nfrom app.prod import total\n\n\n" + install + "\n\n"
             "@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n")
    assert conftest_findings(after) == ("block", [("CONFTEST_PATCHES_PROD", "high", "tests/conftest.py")])


def test_a_definition_inside_a_conftest_fixture_stays_with_the_fixture_passes():
    """The same known gap as in a test file's fixture; the assignment there is reported."""
    head = "import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    return total([(100, 1)])\n"
    assert conftest_findings(head + "    def total(lines):\n        return 105.0\n\n" + tail)[1] == []
    assert conftest_findings(head + "    total = lambda lines: 105.0\n" + tail) == (
        "block", [("CONFTEST_PATCHES_PROD", "high", "tests/conftest.py")])


def test_an_unchanged_definition_in_a_conftest_is_not_scheduled():
    """A conftest's scheduling inventories every test beneath it, so it asks for a changed definition."""
    legacy = ("import pytest\nfrom app.prod import total\n\n\ndef total(lines):\n    return 105.0\n\n\n"
              "@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n")
    _ir, findings, _verdict = judge_files({"tests/conftest.py": legacy}, {"tests/conftest.py": legacy + "\nROWS = []\n"},
                                          {"tests/test_total.py": CONFTEST_TEST})
    assert [f.rule for f in findings if f.rule in ("CONFTEST_PATCHES_PROD", "TEST_PATCHES_SUBJECT")] == []


TRY = IMPORT + "\n\ntry:\n    pass\nexcept Exception:\n    def total(lines):\n        return 0\n\n\n" + TEST
SCHEDULING = [
    # before, after, deny, changed_only, expected
    (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + TEST, (), False, True),
    (BEFORE, DEF + "\n\n" + TEST, (), False, True),                        # the import is on the before side only
    (DEF + "\n\n" + TEST, IMPORT + "\n\n" + DEF + "\n\n" + TEST, (), False, True),   # on the after side only
    (None, IMPORT + "\n\n" + DEF + "\n\n" + TEST, (), False, True),        # an added file
    (BEFORE, IMPORT + "\n\nclass total:\n    pass\n\n\n" + TEST, (), False, True),
    (BEFORE, IMPORT + "\n\ndef test_total():\n    def total(lines):\n        return 0\n", (), False, True),
    (BEFORE, IMPORT + "\n\nif True:\n    def total(lines):\n        return 0\n", (), False, True),
    (BEFORE, IMPORT + "\n\nwith open('x'):\n    def total(lines):\n        return 0\n", (), False, True),
    (ALIAS + TEST, ALIAS + DEF + "\n\n" + TEST, (), False, True),          # captured by an assignment
    # A test file is not compared with its before side: the trace decides what is new.
    (SHADOWED, SHADOWED + "\n\nX = 1\n", (), False, True),
    (SHADOWED, SHADOWED + "\n\nX = 1\n", (), True, False),                 # a conftest is
    (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + TEST, (), True, True),
    (SHADOWED, IMPORT + "\n\ndef total(lines):\n    return 0\n\n\n" + TEST, (), True, True),
    (SHADOWED, IMPORT + "\n\ndef total(lines):\n    \"\"\"Words.\"\"\"\n    return 105.0\n\n\n" + TEST, (), True, False),
    # Where the trace installs nothing, nothing is scheduled.
    (BEFORE, TRY, (), False, False),
    (BEFORE, IMPORT + "\n\nif False:\n    def total(lines):\n        return 0\n", (), False, False),
    (BEFORE, IMPORT + "\n\nif flag():\n    def total(lines):\n        return 0\n", (), False, False),
    (BEFORE, IMPORT + "\n\nfor _ in range(1):\n    def total(lines):\n        return 0\n", (), False, False),
    (BEFORE, IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 0\n\n\n" + TEST, (), False, False),
    (BEFORE, IMPORT + "\n\ndef rows():\n    return []\n\n\n" + TEST, (), False, False),
    (BEFORE, IMPORT + "\n\n" + DEF + "\n\n" + TEST, ("app",), False, False),         # a declared dependency
    (BEFORE, "import pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF + "\n\n" + TEST, (), False, False),
    (FIXTURE_BEFORE, FIXTURE_HEAD + "    def total(lines):\n        return 0\n\n" + FIXTURE_TAIL, (), False, False),
    (FIXTURE_BEFORE, FIXTURE_HEAD.replace("import pytest\n", "import pytest\npytest.fixture = print\n")
     + "    def total(lines):\n        return 0\n\n" + FIXTURE_TAIL, (), False, True),
    (BEFORE, "from pytest import fixture\n" + IMPORT + "\n\n@fixture(autouse=True)\n" + DEF + "\n\n" + TEST, (), False, False),
    # ... unless `pytest.fixture` may be something else in this file.
    (BEFORE, IMPORT + "\n\ndef fixture(function):\n    return function\n\n\n@fixture\n" + DEF, (), False, True),
    (BEFORE, "import pytest\n" + IMPORT + "\npytest.fixture = print\n\n\n@pytest.fixture\n" + DEF, (), False, True),
    (BEFORE, "import pytest\n" + IMPORT + "\nsetattr(pytest, 'fixture', print)\n\n\n@pytest.fixture\n" + DEF, (), False, True),
    (BEFORE, "import pytest\n" + IMPORT + "\npytest = object()\n\n\n@pytest.fixture\n" + DEF, (), False, True),
    (BEFORE, "import fake as pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF, (), False, True),
    (BEFORE, "def broken(:\n", (), False, False),
    ("def broken(:\n", IMPORT + "\n\n" + DEF + "\n\n" + TEST, (), False, True),      # an unparsable before side
]


@pytest.mark.parametrize("before,after,deny,changed_only,expected", SCHEDULING)
def test_the_scheduling_filter_sees_definitions_of_imported_names_where_the_trace_reads(
        before, after, deny, changed_only, expected):
    before = before.encode() if before is not None else None
    assert _definition_rebind(before, after.encode(), set(deny), changed_only=changed_only) is expected
