"""Issue #635: a definition that takes over an imported subject's name is a stand-in.

`total = lambda lines: 105.0` after `from app.prod import total` is
TEST_PATCHES_SUBJECT (THREATMODEL row 90, #88). The same swap written as a
definition passed 0.13.0 with zero findings: a `def` or a class of the name,
with the import kept or deleted. Production stays buggy and the assertion
stays byte-identical; the test calls the local name.

The trace now treats a `def` or `class` that rebinds a captured import as it
treats the assignment: in the module body of a test file or a conftest, in
the test, and in a same-file helper function the test calls, as a direct
statement or under `with` or a literal `if`.

A definition the diff did not touch installs nothing. "Not touched" means
that everything binding its name, in its scope and the scopes around it, is
the same on both sides; such a definition is read exactly as before #635.

Not read, for the assignment as for the definition: a statement under `try`,
a loop, `match` or an `if` whose test is not a literal. So an optional import
of the name after the definition changes nothing, as it changes nothing after
an assignment. Not read for the definition only: the body of a pytest fixture,
which the fixture passes judge.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.standin_installations import _definition_identity, _definition_rebind, _settled
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.ir.astutil import stable_dump
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
SHADOWED = IMPORT + "\n\n" + DEF + "\n\n" + TEST

# name -> (before, after, the evidence line)
POSITIVES = {
    "module_level_def": (BEFORE, SHADOWED, "def total(lines):"),
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
    # A standard-library import of the name in front of the definition is no cover,
    # in the module or inside the test.
    "decoy_import_then_def": (
        BEFORE, IMPORT + "from os.path import join as total\n\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "decoy_import_and_def_inside_the_test": (
        BEFORE,
        IMPORT + "\n\ndef test_total():\n    from operator import add as total\n\n"
        "    def total(lines):\n        return 105.0\n\n    assert total([(100, 1)]) == 105.0\n", "def total(lines):"),
    # The name was captured by an assignment, not by an import statement.
    "alias_then_def": (ALIAS + TEST, ALIAS + DEF + "\n\n" + TEST, "def total(lines):"),
    "alias_then_def_twice": (ALIAS + TEST, ALIAS + DEF + "\n\n" + DEF + "\n\n" + TEST, "def total(lines):"),
    "alias_then_def_then_lambda": (
        ALIAS + TEST, ALIAS + DEF + "\n\ntotal = lambda lines: 105.0\n\n\n" + TEST, "total = lambda lines: 105.0"),
    # Where the assignment spelling is read, the definition is too.
    "def_in_a_helper_the_test_asserts_through": (
        HELPER_BEFORE,
        IMPORT + "\n\ndef computed():\n    def total(lines):\n        return 105.0\n\n"
        "    return total([(100, 1)])\n\n\ndef test_total():\n    assert computed() == 105.0\n", "def total(lines):"),
    # A fixture decorator does not stop the definition from binding the module-level name.
    "decoy_fixture_decorator": (
        BEFORE,
        IMPORT + "\n\ndef fixture(function):\n    return function\n\n\n@fixture\n" + DEF + "\n\n" + TEST,
        "def total(lines):"),
    "patched_fixture_decorator": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\npytest.fixture = lambda function: function\n\n\n@pytest.fixture\n"
        + DEF + "\n\n" + TEST, "def total(lines):"),
    "fixture_decorated_def_then_unwrapped": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF + "\n\ntotal = total.__wrapped__\n\n\n" + TEST,
        "total = total.__wrapped__"),
    "fixture_decorated_def_under_another_decorator": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\n\ndef plain(fixture):\n    return fixture.__wrapped__\n\n\n@plain\n@pytest.fixture\n"
        + DEF + "\n\n" + TEST, "def total(lines):"),
    # An optional import that cannot restore production leaves the definition reported.
    "def_then_optional_import_of_a_missing_module": (
        BEFORE, SHADOWED.replace(TEST, "try:\n    from app.fast import total\nexcept ImportError:\n    pass\n\n\n" + TEST),
        "def total(lines):"),
    "def_then_optional_import_of_a_standard_library_name": (
        BEFORE, DEF + "\n\ntry:\n    from math import fsum as total\nexcept ImportError:\n    pass\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_unknown_branch_importing_a_missing_module": (
        BEFORE, "import sys\n" + IMPORT + "\n\n" + DEF + "\n\nif sys.platform == 'plan9':\n    from app.fast import total\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_type_checking_import": (
        BEFORE, "from typing import TYPE_CHECKING\n\n\n" + DEF + "\n\nif TYPE_CHECKING:\n    from app.prod import total\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_import_in_an_except_arm": (
        BEFORE, DEF + "\n\ntry:\n    pass\nexcept ImportError:\n    from app.prod import total\n\n\n" + TEST,
        "def total(lines):"),
    "def_then_import_under_a_branch_no_test_run_takes": (
        BEFORE, SHADOWED.replace(TEST, "if __name__ == \"__main__\":\n    from app.prod import total\n\n\n" + TEST),
        "def total(lines):"),
    # The test reads the name through its own module object.
    "read_through_request_module": (
        IMPORT + "\n\ndef test_total(request):\n    assert request.module.total([(100, 1)]) == 105.0\n",
        IMPORT + "\n\n" + DEF + "\n\ndef test_total(request):\n    assert request.module.total([(100, 1)]) == 105.0\n",
        "def total(lines):"),
    # The definition was already in the file, where it did not bind the name the test reads.
    "import_moved_above_the_def": (DEF + "\n\n" + IMPORT + "\n\n" + TEST, SHADOWED, "def total(lines):"),
    "moved_out_of_an_unused_helper": (
        IMPORT + "\n\ndef unused():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n" + TEST,
        SHADOWED, "def total(lines):"),
    "copied_out_of_an_unused_helper": (
        IMPORT + "\n\ndef unused():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n" + TEST,
        IMPORT + "\n\n" + DEF + "\n\ndef unused():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n" + TEST,
        "def total(lines):"),
    "dead_branch_made_live": (
        IMPORT + "\n\nif False:\n    def total(lines):\n        return 105.0\n\n\n" + TEST,
        IMPORT + "\n\nif True:\n    def total(lines):\n        return 105.0\n\n\n" + TEST, "def total(lines):"),
}


def judged(before, after, production=PRODUCTION, context=None):
    ir, findings, verdict = run(before, after, production, context=context)
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


@pytest.mark.parametrize("edited", [
    "def total(lines):\n    return 105.0\n",                          # the body
    "def total(rows):\n    return sum(p * q for p, q in rows) * 1.05\n",  # a parameter's name
    "def total(lines, rate=1.05):\n    return sum(p * q for p, q in lines) * rate\n",  # an added parameter
])
def test_an_edited_local_definition_is_a_new_effect_like_an_edited_lambda(edited):
    before = IMPORT + "\n\ndef total(lines):\n    return sum(p * q for p, q in lines) * 1.05\n\n\n" + TEST
    verdict, standins, _events = judged(before, IMPORT + "\n\n" + edited + "\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_fixture_that_takes_over_a_name_a_test_still_reads_is_reported():
    """The module-level name is now the fixture object, whatever the test goes on to do with it."""
    before = "import pytest\nfrom app import prod\n\n\ndef test_total():\n    assert prod.total([(100, 1)]) == 105.0\n"
    after = before.replace("def test_total", "@pytest.fixture\ndef prod():\n    return [(100, 1)]\n\n\ndef test_total")
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert [(target, text) for _path, _unit, target, text, _span in events] == [("app.prod", "def prod():")]
    # A test that takes the fixture as a parameter reads the parameter, not the module-level name.
    requested = after.replace("def test_total():\n    assert prod.total([(100, 1)]) == 105.0",
                              "def test_total(prod):\n    assert prod == [(100, 1)]")
    _verdict, standins, events = judged(before, requested)
    assert standins == [] and events == []


def test_evidence_text_has_no_carriage_return():
    _verdict, _standins, events = judged(BEFORE.replace("\n", "\r\n"), SHADOWED.replace("\n", "\r\n"))
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


UNTOUCHED = {
    # The same definition on both sides, consumed by the same test. It moves
    # down two lines, so an identity with positions would differ.
    "definition_unchanged_and_shifted": (
        SHADOWED, IMPORT + "\nROWS = [(100, 1)]\n\n\n" + DEF + "\n\n" + TEST + "\n\ndef test_other():\n    assert ROWS\n"),
    "docstring_added": (
        SHADOWED, IMPORT + "\n\ndef total(lines):\n    \"\"\"The fixed total.\"\"\"\n    return 105.0\n\n\n" + TEST),
    "annotations_added": (SHADOWED, IMPORT + "\n\ndef total(lines: list) -> float:\n    return 105.0\n\n\n" + TEST),
    # An existing test starts to assert through a definition the diff did not touch.
    "a_test_starts_to_assert_through_it": (
        IMPORT + "\n\n" + DEF + "\n\ndef test_total():\n    assert 1 + 1 == 2\n", SHADOWED),
    # Refactors of a test whose before side the trace could not read.
    "loop_to_parametrize": (
        "import pytest\n" + IMPORT + "\n\n" + DEF + "\n\ndef test_total():\n"
        "    for lines, expected in [([(100, 1)], 105.0)]:\n        assert total(lines) == expected\n",
        "import pytest\n" + IMPORT + "\n\n" + DEF + "\n\n@pytest.mark.parametrize('lines, expected', [([(100, 1)], 105.0)])\n"
        "def test_total(lines, expected):\n    assert total(lines) == expected\n"),
    "comprehension_to_asserts": (
        IMPORT + "\n\n" + DEF + "\n\ndef test_total():\n    assert all(total(lines) == 105.0 for lines in [[(100, 1)]])\n",
        SHADOWED),
}


@pytest.mark.parametrize("name", sorted(UNTOUCHED))
def test_a_definition_the_diff_did_not_touch_installs_nothing(name):
    before, after = UNTOUCHED[name]
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


def test_a_second_assignment_after_an_untouched_definition_is_still_reported():
    """The definition is settled no longer once something else binds its name beside it."""
    verdict, standins, events = judged(SHADOWED, IMPORT + "\n\n" + DEF + "\ntotal = lambda lines: 105.0\n\n\n" + TEST)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["total = lambda lines: 105.0"]


NEGATIVES = {
    # Faking the standard library is hygiene, as it is for the assignment.
    "standard_library_name": (
        "from os.path import join\n" + IMPORT + "\n\ndef test_join():\n    assert join('a', 'b')\n\n\n" + TEST,
        "from os.path import join\n" + IMPORT + "\n\ndef join(a, b):\n    return a + '/' + b\n\n\n"
        "def test_join():\n    assert join('a', 'b')\n\n\n" + TEST, None),
    # A method binds a class attribute; the test still reads the import.
    "method_with_the_name": (
        IMPORT + "\n\nclass TestTotals:\n    def test_total(self):\n        assert total([(100, 1)]) == 105.0\n",
        IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 'label'\n\n"
        "    def test_total(self):\n        assert total([(100, 1)]) == 105.0\n", None),
    "another_name": (
        BEFORE,
        IMPORT + "\n\ndef rows():\n    return [(100, 1)]\n\n\ndef test_total():\n    assert total(rows()) == 105.0\n", None),
    # Local to a helper that the test calls for something else.
    "definition_inside_a_helper_called_for_another_value": (
        IMPORT + "\n\ndef rows():\n    return [(100, 1)]\n\n\ndef test_total():\n    assert total(rows()) == 105.0\n",
        IMPORT + "\n\ndef rows():\n    def total(lines):\n        return 'label'\n\n    return [(100, 1)]\n\n\n"
        "def test_total():\n    assert total(rows()) == 105.0\n", None),
    # A module-level definition does not take over an import made inside the test.
    "import_inside_the_test": (
        "def test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n",
        DEF + "\n\ndef test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n", None),
    # An import under `if TYPE_CHECKING:` is not one the trace captures, so a runtime class of the name takes over nothing.
    "type_checking_import_and_runtime_class": (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.prod import total\n\n\n"
        "def test_total():\n    assert 1 + 1 == 2\n",
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.prod import total\n\n\n"
        "class total:\n    pass\n\n\ndef test_total():\n    assert total() is not None\n", None),
}


@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_a_definition_that_does_not_take_over_the_subject_reports_nothing(name):
    before, after, context = NEGATIVES[name]
    _verdict, standins, events = judged(before, after, context=context)
    assert standins == [] and events == []


OPTIONAL = {
    "try": "try:\n    from app.prod import total\nexcept ImportError:\n    pass\n",
    "version_branch": "import sys\n\nif sys.version_info >= (3, 11):\n    from app.prod import total\n",
    "another_path": "try:\n    from app.pricing import total\nexcept ImportError:\n    pass\n",
}


@pytest.mark.parametrize("name", sorted(OPTIONAL))
def test_a_fallback_above_an_optional_import_is_reported_as_its_assignment_spelling_is(name):
    """A known cost, pinned: the import wins at run time when it succeeds, and neither spelling reads it.

    Reading it for the definition lost findings 0.13.0 gives and let a branch
    no run takes hide the definition, so the two spellings are judged alike.
    """
    context = {"src/app/pricing.py": b"from app.prod import total\n"}
    for install, evidence in ((DEF, "def total(lines):"), ("total = lambda lines: 105.0\n", "total = lambda lines: 105.0")):
        verdict, standins, events = judged(BEFORE, install + "\n\n" + OPTIONAL[name] + "\n\n" + TEST, context=context)
        assert verdict == "block"
        assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
        assert [text for _path, _unit, _target, text, _span in events] == [evidence]


def test_a_module_level_definition_after_a_deleted_function_scope_import_is_a_known_gap():
    """Pinned, not wanted: the test imported inside its body; the diff deletes that and defines the name above.

    The assignment spelling of the same diff passes 0.13.0 as well.
    """
    before = "def test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n"
    for install in (DEF, "total = lambda lines: 105.0\n"):
        _verdict, standins, events = judged(before, install + "\n\n" + TEST)
        assert standins == [] and events == []


FIXTURE_HEAD = "import pytest\n" + IMPORT + "\n\n@pytest.fixture\ndef amount():\n"
FIXTURE_TAIL = "    return total([(100, 1)])\n\n\ndef test_total(amount):\n    assert amount == 105.0\n"


@pytest.mark.parametrize("inner", ["    def total(lines):\n        return 105.0\n\n", "    class total(float):\n        pass\n\n"])
def test_a_definition_inside_a_fixture_body_stays_with_the_fixture_passes(inner):
    """Known gap, pinned: the assignment in the same place is reported, the definition is not.

    The fixture passes report a local implementation only in the shapes they
    prove (tests/test_generator_fixture_subjects.py pins what they decline).
    """
    _verdict, standins, events = judged(FIXTURE_BEFORE, FIXTURE_HEAD + inner + FIXTURE_TAIL)
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


def test_the_fixture_pass_reports_a_fixture_s_inner_definition_as_before():
    """One finding, the fixture pass's: the inner def is in a fixture's body, which this rule does not read."""
    before = ("from app.prod import square\ndef test_square():\n"
              "    checks = (square(i) == i * i for i in range(2, 5))\n    assert all(checks)\n")
    after = ("import pytest\nfrom app.prod import square\n@pytest.fixture\ndef correct_square():\n"
             "    def square(x):\n        return x * x\n    return square\n"
             "@pytest.mark.parametrize(\"x, expected\", [(2, 4), (3, 9), (4, 16)])\n"
             "def test_square(correct_square, x, expected):\n    assert correct_square(x) == expected\n")
    _verdict, standins, events = judged(before, after, "def square(x):\n    return x * 2\n")
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_square")]
    assert [event[3] for event in events] == ["assert correct_square(x) == expected"]


@pytest.mark.parametrize("carried", [
    "total = total", "total = staticmethod(total).__func__", "total = functools.wraps(total)(lambda lines: 105.0)"])
def test_an_assignment_after_the_definition_is_the_one_finding(carried):
    """A definition row is dropped where an assignment in the same test reports the same target."""
    after = "import functools\n" + IMPORT + "\n\n" + DEF + "\n\n" + carried + "\n\n\n" + TEST
    _verdict, standins, events = judged("import functools\n" + BEFORE, after)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == [carried]


def test_a_new_assignment_through_an_existing_wrapper_is_reported():
    """The wrapper forwards to production on both sides; the diff rebinds the name through it."""
    wrapper = "import functools\nfrom app import prod\n" + IMPORT + "\n\ndef total(lines):\n    return prod.total(lines)\n\n\n"
    carried = "total = functools.wraps(total)(lambda lines: 105.0)"
    verdict, standins, events = judged(wrapper + TEST, wrapper + carried + "\n\n\n" + TEST)
    assert verdict == "block"
    assert [text for _path, _unit, _target, text, _span in events] == [carried]


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
    _verdict, standins, events = judged(before, SHADOWED)
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(target, text) for _path, _unit, target, text, _span in events] == [
        ("app.prod.total", "assert total([(100, 1)]) == 105.0")]


# What 0.13.0 reports beside a local class or wrapper of the name must still be reported.
MONEY = "class Money:\n    @staticmethod\n    def total(lines):\n        return sum(p * q for p, q in lines)\n"
MONEY_TEST = "def test_total():\n    assert Money.total([(100, 1)]) == 105.0\n"
MONEY_IMPORT = "from app.prod import Money\n"
SHADOW_CLASS = "class Money(Money):\n    pass\n"
MONEY_SHADOW = MONEY_IMPORT + "\n\n" + SHADOW_CLASS + "\n\n"
MONEY_PATCHED = "def test_total():\n    Money.total = staticmethod(lambda lines: 105.0)\n    assert Money.total([(100, 1)]) == 105.0\n"
OPTIONAL_MONEY = "try:\n    from app.prod import Money\nexcept ImportError:\n    pass\n\n\n"
RELEASED = {
    # An attribute written on an existing shadow class still names production.
    "attribute_on_an_existing_shadow_class": (
        MONEY_SHADOW + MONEY_TEST, MONEY_SHADOW + MONEY_PATCHED, None, ["app.prod.Money.total"]),
    "setattr_on_an_existing_shadow_class": (
        MONEY_SHADOW + MONEY_TEST,
        MONEY_SHADOW + MONEY_PATCHED.replace("Money.total = staticmethod(lambda lines: 105.0)",
                                             "setattr(Money, 'total', staticmethod(lambda lines: 105.0))"),
        None, ["app.prod.Money.total"]),
    # A stand-in installed in front of an existing shadow class is not replaced by the class.
    "assignment_before_an_existing_shadow_class": (
        MONEY_SHADOW + MONEY_TEST,
        MONEY_IMPORT + "\n\nMoney = type('Money', (), {'total': staticmethod(lambda lines: 105.0)})\n\n\n"
        + SHADOW_CLASS + "\n\n" + MONEY_TEST, None, ["app.prod.Money"]),
    "import_rebound_before_an_existing_shadow_class": (
        MONEY_SHADOW + MONEY_TEST, "from tests.fakes import Money\n\n\n" + SHADOW_CLASS + "\n\n" + MONEY_TEST,
        {"tests/__init__.py": b"", "tests/fakes.py": b"class Money:\n    @staticmethod\n    def total(lines):\n        return 105.0\n"},
        ["app.prod.Money"]),
    # An optional import of the provider after a class of the name leaves the name's alias as it was.
    "attribute_after_an_optional_import_beside_an_existing_shadow_class": (
        MONEY_SHADOW + MONEY_TEST, MONEY_SHADOW + OPTIONAL_MONEY + MONEY_PATCHED, None, ["app.prod.Money.total"]),
    # A new class is reported too; the attribute's finding, which is 0.13.0's, stays.
    "attribute_after_an_optional_import_beside_a_new_class": (
        MONEY_IMPORT + "\n\n" + MONEY_TEST, MONEY_SHADOW + OPTIONAL_MONEY + MONEY_PATCHED, None,
        ["app.prod.Money", "app.prod.Money.total"]),
    # A closed `mock.patch.object` on an existing shadow class.
    "closed_patch_object_on_an_existing_shadow_class": (
        "from unittest import mock\n" + MONEY_SHADOW + MONEY_TEST,
        "from unittest import mock\n" + MONEY_SHADOW + "def test_total():\n"
        "    with mock.patch.object(Money, 'total', return_value=105.0) as fake:\n        assert fake([(100, 1)]) == 105.0\n",
        None, ["app.prod.Money.total"]),
}


@pytest.mark.parametrize("name", sorted(RELEASED))
def test_what_the_release_reports_beside_a_local_class_is_still_reported(name):
    before, after, context, targets = RELEASED[name]
    verdict, standins, events = judged(before, after, MONEY, context)
    assert verdict == "block"
    assert [row[:3] for row in standins] == [("TEST_PATCHES_SUBJECT", "high", "test_total")] * len(targets)
    assert [target for _path, _unit, target, _text, _span in events] == targets


WRAPPER_HEAD = "from app import prod\n" + IMPORT + "\n\n"
FORWARD = "def total(lines):\n    return prod.total(lines)\n"
FAILING = "try:\n    from app.fast import total\nexcept ImportError:\n    pass\n"
PATCHED = "def test_total():\n    prod.total = lambda lines: 105.0\n    assert total([(100, 1)]) == 105.0\n"
BESIDE_A_WRAPPER = {
    # A new wrapper that writes the attribute itself, then an optional import that fails.
    "wrapper_that_patches_then_a_failing_optional_import": (
        WRAPPER_HEAD + TEST,
        WRAPPER_HEAD + "def total(lines):\n    prod.total = lambda rows: 105.0\n    return prod.total(lines)\n\n\n"
        + FAILING + "\n\n" + TEST, ("app.prod.total", "prod.total = lambda rows: 105.0")),
    # A new forwarding wrapper, a failing optional import, and the attribute written in the test.
    "new_wrapper_failing_optional_import_and_attribute_in_the_test": (
        WRAPPER_HEAD + TEST, WRAPPER_HEAD + FORWARD + "\n\n" + FAILING + "\n\n" + PATCHED,
        ("app.prod.total", "prod.total = lambda lines: 105.0")),
    # The wrapper and the import were there; only the wrapper is edited beside the attribute write.
    "edited_wrapper_beside_an_optional_import": (
        WRAPPER_HEAD + FORWARD + "\n\n" + FAILING + "\n\n" + TEST,
        WRAPPER_HEAD + FORWARD.replace("return prod.total(lines)", "return prod.total(list(lines))") + "\n\n" + FAILING
        + "\n\n" + PATCHED, ("app.prod.total", "prod.total = lambda lines: 105.0")),
    # The optional import succeeds and imports what the module-level write installed.
    "module_level_write_wrapper_and_an_optional_import_that_succeeds": (
        WRAPPER_HEAD + TEST,
        WRAPPER_HEAD + "prod.total = lambda lines: 105.0\n\n\n" + FORWARD + "\n\n"
        + FAILING.replace("app.fast", "app.prod") + "\n\n" + TEST, ("app.prod.total", "prod.total = lambda lines: 105.0")),
    # Both sides rebind the name through a helper; the diff deletes the local def in front of that.
    "definition_removed_in_front_of_an_assignment": (
        IMPORT + "\n\ndef fixed(function):\n    return lambda lines: 105.0\n\n\ndef total(lines):\n    return 0\n\n\n"
        "total = fixed(total)\n\n\n" + TEST,
        IMPORT + "\n\ndef fixed(function):\n    return lambda lines: 105.0\n\n\ntotal = fixed(total)\n\n\n" + TEST,
        ("app.prod.total", "total = fixed(total)")),
}


@pytest.mark.parametrize("name", sorted(BESIDE_A_WRAPPER))
def test_what_the_release_reports_beside_a_local_def_is_still_reported(name):
    """Each of these blocks on 0.13.0 with this evidence; the definition's own row must not replace it."""
    before, after, event = BESIDE_A_WRAPPER[name]
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(target, text) for _path, _unit, target, text, _span in events] == [event]


def test_an_untouched_definition_in_a_file_scheduled_for_another_reason_installs_nothing():
    """The trace runs here whatever the definition filter says, so this pins the trace's own reading."""
    head = "import app.prod as billing\n" + IMPORT + "\n\n" + DEF + "\n\ndef test_total(monkeypatch):\n"
    patch = "    monkeypatch.setattr(billing, \"rate\", 0.05)\n"
    before = head + patch + "    assert billing.rate == 0.05\n"
    _verdict, standins, events = judged(before, before + "    assert total([(100, 1)]) == 105.0\n", PRODUCTION + "rate = 0.0\n")
    assert [target for _path, _unit, target, _text, _span in events if target == "app.prod.total"] == []
    assert [row for row in standins if "app.prod.total " in row[3]] == []


def test_a_closed_patch_of_an_attribute_of_a_new_class_is_still_one():
    """The class carries its own effect; the patched attribute's result must still be followed."""
    before = "from unittest import mock\n" + MONEY_IMPORT + "\n\n" + MONEY_TEST
    after = ("from unittest import mock\n" + MONEY_SHADOW + "def test_total():\n"
             "    with mock.patch.object(Money, 'total', return_value=105.0) as fake:\n        assert fake([(100, 1)]) == 105.0\n")
    verdict, _standins, events = judged(before, after, MONEY)
    assert verdict == "block"
    assert "app.prod.Money.total" in [target for _path, _unit, target, _text, _span in events]


def test_a_renamed_provider_under_an_untouched_definition_is_not_a_new_installation():
    """The production module is renamed and the import follows; the local subclass is the one it was."""
    def files(module):
        return {f"{module}.py": MONEY, "tests/test_money.py": f"from {module} import Money\n\n\n" + SHADOW_CLASS + "\n\n" + MONEY_TEST}

    before, after = files("money"), files("pricing")
    paths = sorted(before.keys() | after.keys())
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before[path].encode() if path in before else None, after[path].encode() if path in after else None)
               for path in paths]
    snapshot = {path: source.encode() for path, source in after.items()}
    _ir, findings, _verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 11, 20),
                                      root_reader=snapshot.get,
                                      root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                                      root_path_lister=lambda: sorted(snapshot),
                                      root_batch_reader=lambda wanted: {path: snapshot.get(path) for path in wanted})
    assert [f.message for f in findings if f.rule == "TEST_PATCHES_SUBJECT"] == []


def test_an_attribute_standin_beside_a_wrapper_and_a_type_checking_import_is_still_reported():
    wrapper = ("from typing import TYPE_CHECKING\n\nfrom app import prod\n" + IMPORT
               + "\n\ndef total(lines):\n    return prod.total(lines)\n\n\n")
    after = wrapper + "if TYPE_CHECKING:\n    from app.prod import total\n\n\n" + (
        "def test_total():\n    prod.total = lambda lines: 105.0\n    assert total([(100, 1)]) == 105.0\n")
    verdict, _standins, events = judged(wrapper + TEST, after)
    assert verdict == "block"
    assert [(target, text) for _path, _unit, target, text, _span in events] == [
        ("app.prod.total", "prod.total = lambda lines: 105.0")]


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


def conftest_findings(after, before=CONFTEST):
    _ir, findings, verdict = judge_files({"tests/conftest.py": before}, {"tests/conftest.py": after},
                                         {"tests/test_total.py": CONFTEST_TEST})
    return verdict, [(f.rule, f.severity, f.path, f.fingerprint) for f in findings
                     if f.rule in ("CONFTEST_PATCHES_PROD", "TEST_PATCHES_SUBJECT")]


def conftest_with(install):
    return ("import pytest\nfrom app.prod import total\n\n\n" + install + "\n\n"
            "@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n")


@pytest.mark.parametrize("install", ["def total(lines):\n    return 105.0\n", "total = lambda lines: 105.0\n"])
def test_a_definition_in_a_conftest_module_body_is_reported_as_the_assignment_is(install):
    verdict, found = conftest_findings(conftest_with(install))
    assert verdict == "block"
    assert [row[:3] for row in found] == [("CONFTEST_PATCHES_PROD", "high", "tests/conftest.py")]


def test_a_conftest_definition_s_fingerprint_follows_its_body():
    """An exemption is keyed by this fingerprint; one granted for a wrapper must not cover a stand-in."""
    def fingerprint(body):
        return conftest_findings(conftest_with("def total(lines):\n" + body))[1][0][3]

    forwarding = fingerprint("    return sum(p * q for p, q in lines)\n")
    assert fingerprint("    return 105.0\n") != forwarding
    assert fingerprint("    \"\"\"Forward.\"\"\"\n    return sum(p * q for p, q in lines)\n") == forwarding


def test_a_conftest_definition_s_evidence_text_is_the_same_on_every_python():
    """Pinned as a literal: from 3.12 a def dumps an empty `type_params`, which must not reach the digest."""
    _ir, findings, _verdict = judge_files({"tests/conftest.py": CONFTEST},
                                          {"tests/conftest.py": conftest_with("def total(lines):\n    return 105.0\n")},
                                          {"tests/test_total.py": CONFTEST_TEST})
    assert [f.after.text for f in findings if f.rule == "CONFTEST_PATCHES_PROD"] == [
        "def total(lines):  # definition d7ac38bf9b7c"]


def test_a_definition_inside_a_conftest_fixture_stays_with_the_fixture_passes():
    """The same known gap as in a test file's fixture; the assignment there is reported."""
    head = "import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    return total([(100, 1)])\n"
    assert conftest_findings(head + "    def total(lines):\n        return 105.0\n\n" + tail)[1] == []
    verdict, found = conftest_findings(head + "    total = lambda lines: 105.0\n" + tail)
    assert verdict == "block" and [row[:3] for row in found] == [("CONFTEST_PATCHES_PROD", "high", "tests/conftest.py")]


def test_an_untouched_definition_in_a_conftest_installs_nothing_when_a_fixture_starts_to_read_it():
    """The diff only makes the fixture read the name; the definition above it is as it was."""
    legacy = ("import pytest\nfrom app.prod import total\n\n\ndef total(lines):\n    return 105.0\n\n\n"
              "@pytest.fixture\ndef amount():\n    return 105.0\n")
    reading = legacy.replace("def amount():\n    return 105.0\n", "def amount():\n    return total([(100, 1)])\n")
    assert reading != legacy and conftest_findings(reading, legacy)[1] == []
    # With the definition edited in the same diff, it is reported.
    edited = reading.replace("def total(lines):\n    return 105.0\n", "def total(lines):\n    return 105.0 + 0\n")
    assert [row[0] for row in conftest_findings(edited, legacy)[1]] == ["CONFTEST_PATCHES_PROD"]


TRY = IMPORT + "\n\ntry:\n    pass\nexcept Exception:\n    def total(lines):\n        return 0\n\n\n" + TEST
UNUSED_HELPER = IMPORT + "\n\ndef unused():\n    def total(lines):\n        return 105.0\n\n    return total\n\n\n" + TEST
SCHEDULING = [
    # before, after, deny, expected
    (BEFORE, SHADOWED, (), True),
    (BEFORE, DEF + "\n\n" + TEST, (), True),                               # the import is on the before side only
    (DEF + "\n\n" + TEST, SHADOWED, (), True),                             # the import is new, the definition is not
    (None, SHADOWED, (), True),                                            # an added file
    ("def broken(:\n", SHADOWED, (), True),                                # an unparsable before side
    (BEFORE, IMPORT + "\n\nclass total:\n    pass\n\n\n" + TEST, (), True),
    (BEFORE, IMPORT + "\n\ndef test_total():\n    def total(lines):\n        return 0\n\n    assert total([]) == 0\n", (), True),
    (BEFORE, IMPORT + "\n\nif True:\n    def total(lines):\n        return 0\n\n\n" + TEST, (), True),
    (BEFORE, IMPORT + "\n\nwith open('x'):\n    def total(lines):\n        return 0\n\n\n" + TEST, (), True),
    (ALIAS + TEST, ALIAS + DEF + "\n\n" + TEST, (), True),                  # captured by an assignment
    (SHADOWED, IMPORT + "\n\ndef total(lines):\n    return 0\n\n\n" + TEST, (), True),      # an edited body
    (SHADOWED, IMPORT + "\n\n@staticmethod\n" + DEF + "\n\n" + TEST, (), True),             # a decorator
    (SHADOWED, IMPORT + "\n\n" + DEF + "\ntotal = total\n\n\n" + TEST, (), True),           # another binding beside it
    (SHADOWED, "from app.other import total\n\n\n" + DEF + "\n\n" + TEST, (), True),        # the import changed
    (DEF + "\n\n" + IMPORT + "\n\n" + TEST, SHADOWED, (), True),            # the same words in another order
    (UNUSED_HELPER, SHADOWED, (), True),                                   # moved out of another scope
    (IMPORT + "\n\nif False:\n    def total(lines):\n        return 105.0\n\n\n" + TEST,
     IMPORT + "\n\nif True:\n    def total(lines):\n        return 105.0\n\n\n" + TEST, (), True),
    (BEFORE, "import pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF + "\n\n" + TEST, (), True),   # a fixture binds the name too
    # ... and schedules nothing when the name is only ever received as a parameter.
    (BEFORE, "import pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF + "\n\ndef test_total(total):\n    assert total\n", (), False),
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF + "\n\ndef test_total(total):\n    assert total\n", (), False),
    (BEFORE, "import pytest\n" + IMPORT + "\n\n@pytest.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert total\n\n\ndef test_other(value=total):\n    assert value\n", (), True),
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert total\n\n\ndef test_other():\n    total = 1\n    assert total\n", (), False),   # a local
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total, request):\n    assert request.module.total\n", (), True),                       # an attribute
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert globals()[\"total\"]\n", (), True),                                 # a string
    # ... or read only above the definition, as the module is loaded: that read sees the import.
    (BEFORE, "import wrappers\n" + IMPORT + "\nDEFAULT = total([])\n\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert total\n", (), False),
    (BEFORE, IMPORT + "\n\ndef early():\n    return total([])\n\n\n" + DEF + "\n\ndef test_total(total):\n    assert early()\n",
     (), True),                                                             # a function above it runs later
    ("import os\n" + BEFORE, "import os\nfrom os.path import join as total\n\n\n" + DEF + "\n\n" + TEST, ("os",), True),   # one owned import is enough
    (SHADOWED, "from app.prod import *\n" + DEF + "\n\n" + TEST, (), True),                # the import became a star import
    (SHADOWED, SHADOWED.replace(DEF, DEF + "\nfrom app.extra import *\n"), (), True),        # a star import below it
    (SHADOWED, SHADOWED.replace(DEF, DEF + "\n\ntry:\n    from app.prod import total\nexcept ImportError:\n    pass\n"),
     (), True),                                                             # an optional import of the name is a binding
    # A definition the diff did not touch schedules nothing, whatever else changed.
    (SHADOWED, SHADOWED.replace("import total", "import total, other"), (), False),          # the import line gains a name
    (SHADOWED.replace("import total", "import total, other"), SHADOWED.replace("import total", "import other, total"),
     (), False),                                                            # its names re-sorted
    (SHADOWED.replace("import total", "import total as total"), SHADOWED, (), False),         # a useless alias removed
    (SHADOWED, "from app.extra import *\n" + SHADOWED, (), False),                            # a star import above it
    (SHADOWED, "from typing import TYPE_CHECKING\n" + SHADOWED
     + "\n\nif TYPE_CHECKING:\n    from app.types import total\n", (), False),                # no run takes that branch
    (SHADOWED, SHADOWED + "\n\nX = 1\n", (), False),
    (SHADOWED, "import os\n" + SHADOWED.replace("assert total", "assert os and total"), (), False),
    (SHADOWED, IMPORT + "\n\ndef total(lines):\n    \"\"\"Words.\"\"\"\n    return 105.0\n\n\n" + TEST, (), False),
    (SHADOWED, IMPORT + "\n\ndef total(lines: list) -> float:\n    return 105.0\n\n\n" + TEST, (), False),
    (UNUSED_HELPER, UNUSED_HELPER + "\n\nX = 1\n", (), False),
    # Where the trace installs nothing, nothing is scheduled.
    (FIXTURE_BEFORE, FIXTURE_HEAD + "    def total(lines):\n        return 0\n\n" + FIXTURE_TAIL, (), False),   # a pytest fixture's body
    (BEFORE, TRY, (), False),
    (BEFORE, IMPORT + "\n\nif False:\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nif flag():\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nfor _ in range(1):\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nmatch 1:\n    case 1:\n        def total(lines):\n            return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\ndef rows():\n    return []\n\n\n" + TEST, (), False),
    (BEFORE, SHADOWED, ("app",), False),                                   # a declared dependency
    (BEFORE, "def broken(:\n", (), False),
    # A fixture's body is read when the decorator is not, or may not be, pytest's.
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\ndef amount():\n    def total(lines):\n        return 0\n\n"
     + FIXTURE_TAIL, (), True),
    (FIXTURE_BEFORE, FIXTURE_HEAD.replace("import pytest\n", "import pytest\npytest.fixture = print\n")
     + "    def total(lines):\n        return 0\n\n" + FIXTURE_TAIL, (), True),
    # A name the definition's own scope chain does not capture.
    ("def test_total():\n    from app.prod import total\n\n    assert total\n",
     DEF + "\n\ndef test_total():\n    from app.prod import total\n\n    assert total\n\n\ndef test_other():\n    assert total\n",
     (), False),
    ("from app import prod\n\n\ndef test_total():\n    total = prod.total\n    assert total\n",
     "from app import prod\n\n\n" + DEF + "\n\ndef test_total():\n    total = prod.total\n    assert total\n\n\n"
     "def test_other():\n    assert total\n", (), False),
    ("from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.prod import total\n",
     "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.prod import total\n\n\nclass total:\n    pass\n\n\n"
     + TEST, (), False),
    ("try:\n    from app.prod import total\nexcept ImportError:\n    total = None\n",
     "try:\n    from app.prod import total\nexcept ImportError:\n    total = None\n\n\n" + DEF + "\n\n" + TEST, (), False),
]


@pytest.mark.parametrize("before,after,deny,expected", SCHEDULING)
def test_the_scheduling_filter_asks_for_a_touched_definition_of_a_captured_name(before, after, deny, expected):
    before = before.encode() if before is not None else None
    assert _definition_rebind(before, after.encode(), set(deny)) is expected


def test_settled_names_the_definitions_whose_binding_is_the_same_on_both_sides():
    after = SHADOWED + "\n\ndef helper():\n    def total(lines):\n        return 1\n\n    return total\n"
    assert _settled(ast.parse(SHADOWED), ast.parse(after)) == {("", "total")}
    assert _settled(ast.parse(after), ast.parse(after)) == {("", "total"), ("helper", "total")}
    assert _settled(ast.parse(after), ast.parse(after.replace("return 105.0", "return 0"))) == frozenset()
    # A changed binding of the name in the module unsettles a definition inside a function too.
    assert _settled(ast.parse(after), ast.parse(after.replace("app.prod", "app.other"))) == frozenset()
    assert _settled(None, ast.parse(after)) == frozenset()
    # A definition only the before side has is read as before too.
    assert _settled(ast.parse(after), ast.parse(SHADOWED)) == {("", "total"), ("", "helper"), ("helper", "total")}
    # A `global` declaration and a star import below the definition are bindings of the name.
    assert _settled(ast.parse(SHADOWED), ast.parse(SHADOWED + "\n\ndef rebind():\n    global total\n")) == {("", "total")}
    assert _settled(ast.parse(SHADOWED), ast.parse(SHADOWED.replace(TEST, "global total\n\n\n" + TEST))) == frozenset()
    assert _settled(ast.parse(SHADOWED), ast.parse(SHADOWED + "\nfrom app.extra import *\n")) == frozenset()
    assert _settled(ast.parse(SHADOWED), ast.parse("from app.extra import *\n" + SHADOWED)) == {("", "total")}


def test_a_definition_s_identity_leaves_out_docstrings_pass_and_signature_annotations():
    def identity(source):
        tree = ast.parse(source)
        before = stable_dump(tree)
        value = _definition_identity(tree.body[0])
        assert stable_dump(tree) == before  # the tree is put back as it was
        return value

    plain = identity("def total(lines):\n    return 105.0\n")
    assert identity("def total(lines: list) -> float:\n    \"\"\"Words.\"\"\"\n    return 105.0\n") == plain
    assert identity("def total(lines):\n    pass\n") == identity("def total(lines):\n    \"\"\"Only words.\"\"\"\n")
    assert identity("class total:\n    pass\n") == identity("class total:\n    \"\"\"Only words.\"\"\"\n")
    for edited in ("def total(rows):\n    return 105.0\n", "def total(lines):\n    return 105.5\n",
                   "def total(lines, rate=1):\n    return 105.0\n", "@staticmethod\ndef total(lines):\n    return 105.0\n",
                   "def total(lines):\n    rate: float = 1\n    return 105.0\n"):
        assert identity(edited) != plain


def test_a_deep_expression_in_a_definition_is_not_an_engine_error():
    """0.13.0 passes this honest diff; a copy of the definition used to exhaust the stack."""
    chain = " + ".join(["1"] * 400)
    after = IMPORT + "\n\ndef total(lines):\n    return sum(p * q for p, q in lines) + (" + chain + ") * 0\n\n\n" + TEST
    verdict, standins, _events = judged(BEFORE, after)
    assert verdict == "block" and len(standins) == 1
    # Far deeper than a parser accepts from source: the identity is still computed, and the tree left as it was.
    definition = ast.parse("def total(lines):\n    return 1\n").body[0]
    deep = ast.Constant(value=1)
    for _ in range(5000):
        deep = ast.BinOp(left=deep, op=ast.Add(), right=ast.Constant(value=1))
    definition.body[0].value = deep
    assert _definition_identity(definition).startswith("definition:FunctionDef(")
    assert definition.body[0].value is deep
