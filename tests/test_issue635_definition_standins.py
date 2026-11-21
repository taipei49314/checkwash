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
an assignment.

A definition in a fixture's body is read like one anywhere else. One thing
stays with the fixture passes: a function a fixture defines in its own body
and hands, as its whole value, to a test that takes the fixture as a
parameter, which they judge under their own proof obligations
(tests/test_generator_fixture_subjects.py). Another fixture that receives it
receives it with the definition's effect, and a class is read wherever it
goes.
"""
import ast
import datetime
import time

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import standin_installations
from checkwash.frontends.python.standin_installations import (
    _definition_digest,
    _definition_identity,
    _definition_rebind,
    _holds_new_definition,
    _import_target,
    _settled,
)
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
    # A statement under `try` or an unknown `if` below the definition is not read, whatever it would import.
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
    "function_scope_import_replaced_by_def": (
        "def test_total():\n    from app.prod import total\n\n    assert total([(100, 1)]) == 105.0\n",
        "def test_total():\n    def total(lines):\n        return 105.0\n\n    assert total([(100, 1)]) == 105.0\n",
        "def total(lines):"),
    # `class pytest:` takes the name `pytest` over, so the decorator is the class's and the helper is no fixture.
    "def_in_a_helper_under_a_fixture_of_a_class_named_pytest": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\n\nclass pytest:\n    fixture = staticmethod(lambda function: function)\n\n\n"
        "@pytest.fixture\ndef compute(lines):\n    def total(lines):\n        return 105.0\n\n    return total(lines)\n\n\n"
        "def test_total():\n    assert compute([(100, 1)]) == 105.0\n", "def total(lines):"),
    # The helper is a registered pytest fixture and, unwrapped, a function the test calls.
    "def_in_a_helper_under_an_unwrapped_pytest_fixture": (
        "import pytest\n" + BEFORE,
        "import pytest\n" + IMPORT + "\n\ndef plain(fixture):\n    return fixture.__wrapped__\n\n\n@plain\n@pytest.fixture\n"
        "def compute(lines=()):\n    def total(lines):\n        return 105.0\n\n    return total(lines)\n\n\n"
        "def test_total():\n    assert compute([(100, 1)]) == 105.0\n", "def total(lines):"),
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


@pytest.mark.parametrize("inner", ["    def total(lines):\n        return 105.0\n\n", "    class total(float):\n        pass\n\n",
                                   "    total = lambda lines: 105.0\n"])
def test_a_definition_a_fixture_s_body_uses_is_reported_as_the_assignment_there_is(inner):
    """The fixture calls its own definition of the name and hands the test the result.

    Until the fifth version the definition spelling passed here, in one commit,
    while the assignment spelling blocked on 0.13.0.
    """
    verdict, standins, _events = judged(FIXTURE_BEFORE, FIXTURE_HEAD + inner + FIXTURE_TAIL)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_definition_a_fixture_hands_the_test_as_its_value_stays_with_the_fixture_passes():
    """`return total`: the local function itself is the fixture's value. This rule adds no row of its own."""
    before = FIXTURE_HEAD + "    return total\n\n\ndef test_total(amount):\n    assert amount([(100, 1)]) == 105.0\n"
    after = before.replace("def amount():\n", "def amount():\n    def total(lines):\n        return 105.0\n\n")
    assert after != before
    _verdict, _standins, events = judged(before, after)
    assert "def total(lines):" not in [text for _path, _unit, _target, text, _span in events]


@pytest.mark.parametrize("fixture", [
    "@pytest.fixture\ndef subject():\n    return total\n",                       # the module-level name
    "@pytest.fixture\ndef subject(request):\n    return request.module.total\n",  # through the test's module
])
def test_a_module_level_definition_a_fixture_passes_on_is_reported(fixture):
    """The fixture did not define what it returns; the stand-in is the module's."""
    test = "def test_total(subject):\n    assert subject([(100, 1)]) == 105.0\n"
    before = "import pytest\n" + IMPORT + "\n\n" + fixture + "\n\n" + test
    after = "import pytest\n" + IMPORT + "\n\n" + DEF + "\n\n" + fixture + "\n\n" + test
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_a_module_level_definition_a_conftest_fixture_passes_on_is_reported():
    conftest = b"import pytest\n\n\n@pytest.fixture\ndef subject(request):\n    return request.module.total\n"
    test = "def test_total(subject):\n    assert subject([(100, 1)]) == 105.0\n"
    verdict, standins, _events = judged(IMPORT + "\n\n" + test, IMPORT + "\n\n" + DEF + "\n\n" + test,
                                        context={"tests/conftest.py": conftest})
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_definition_in_a_helper_that_a_fixture_calls_is_reported():
    before = (FIXTURE_HEAD.replace("@pytest.fixture", "def computed():\n    return total([(100, 1)])\n\n\n@pytest.fixture")
              + "    return computed()\n\n\ndef test_total(amount):\n    assert amount == 105.0\n")
    after = before.replace("def computed():\n", "def computed():\n    def total(lines):\n        return 105.0\n\n")
    assert after != before
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_a_fixture_whose_decorator_was_replaced_is_followed_like_a_helper():
    """`pytest.fixture` replaced in the file: the "fixture" is a plain function the test calls."""
    head = "import pytest\n" + IMPORT + "\npytest.fixture = lambda function: function\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    return total([(100, 1)])\n\n\ndef test_total():\n    assert amount() == 105.0\n"
    verdict, standins, events = judged(head + tail, head + "    def total(lines):\n        return 105.0\n\n" + tail)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_the_fixture_pass_reports_a_fixture_s_inner_definition_as_before():
    """One finding, the fixture pass's: the inner def is the fixture's value, which stays with that pass."""
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
    # Of the two definition rows, the one kept is the last definition written.
    line = after.count("\n", 0, after.rindex(DEF)) + 1
    assert [span for _path, _unit, _target, _text, span in events] == [(line, line + 1)]


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


def test_a_definition_a_conftest_fixture_s_body_uses_is_reported_as_the_assignment_there_is():
    head = "import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    return total([(100, 1)])\n"
    for install in ("    def total(lines):\n        return 105.0\n\n", "    total = lambda lines: 105.0\n"):
        verdict, found = conftest_findings(head + install + tail)
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
    (BEFORE, "import wrappers\n" + IMPORT + "\n\ndef early():\n    return total([])\n\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert early()\n", (), True),          # a function above it runs later
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF + "\nDEFAULT = total\n\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert total\n", (), True),            # read below its first definition
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert total\n\n\ndef test_other():\n    global total\n    assert total\n", (), True),  # `global`
    (BEFORE, "import wrappers\n" + IMPORT + "\n\n@wrappers.fixture\n" + DEF
     + "\n\ndef test_total(total):\n    assert (lambda total: total)(1)\n", (), False),                          # a lambda's parameter
    (BEFORE, "import wrappers\n" + IMPORT + "\n\ndef helper():\n    @wrappers.fixture\n    def total(lines):\n        return 0\n\n\n"
     "def test_total():\n    assert total\n", (), False),                         # read outside the definition's scope
    (BEFORE, IMPORT + "\n\n" + DEF + "\n\ndef test_total():\n    assert 1\n", (), True),   # a plain definition needs no reader
    ("from .helpers import total\n\n\n" + TEST, "from .helpers import total\n\n\n" + DEF + "\n\n" + TEST, (), True),  # relative
    (BEFORE, IMPORT + "\n\nif False:\n    pass\nelse:\n    def total(lines):\n        return 0\n\n\n" + TEST, (), True),
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
    (FIXTURE_BEFORE, FIXTURE_HEAD + "    def total(lines):\n        return 0\n\n" + FIXTURE_TAIL, (), True),    # a pytest fixture's body
    # Where the trace installs nothing, nothing is scheduled.
    (BEFORE, TRY, (), False),
    (BEFORE, IMPORT + "\n\nif False:\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nif flag():\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nfor _ in range(1):\n    def total(lines):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nmatch 1:\n    case 1:\n        def total(lines):\n            return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\nclass TestTotals:\n    def total(self):\n        return 0\n\n\n" + TEST, (), False),
    (BEFORE, IMPORT + "\n\ndef rows():\n    return []\n\n\n" + TEST, (), False),
    (BEFORE, SHADOWED, ("app",), False),                                   # a declared dependency
    (BEFORE, "def broken(:\n", (), False),
    # A fixture's body is read whatever its decorator is.
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
    # A definition only the before side has is not set apart: only the after side's definitions are judged.
    assert _settled(ast.parse(after), ast.parse(SHADOWED)) == {("", "total")}
    # A star import below the definition is a binding of the name, and so is a `global` or `nonlocal`
    # declaration in a function or class body; one at module level declares nothing and is not one.
    assert _settled(ast.parse(SHADOWED), ast.parse(SHADOWED + "\n\ndef rebind():\n    global total\n")) == {("", "total")}
    assert _settled(ast.parse(after), ast.parse(after.replace("def helper():\n", "def helper():\n    global total\n"))) \
        == {("", "total")}
    assert _settled(ast.parse(SHADOWED), ast.parse(SHADOWED.replace(TEST, "global total\n\n\n" + TEST))) == {("", "total")}
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
    """A new definition with a deep expression is reported; a copy of the definition used to exhaust the stack."""
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


# ---- Fifth version (2026-11-20) -----------------------------------------------------------------------------------------
# What 0.13.0 reports is reported as it stands: where a definition installs something, the released
# reading runs beside this one, and this rule only adds to it.

FIXED_HEAD = IMPORT + "\n\ndef fixed(function):\n    return lambda lines: 105.0\n\n\n"
LOCAL = "def total(lines):\n    return 0\n"
CARRIED = "total = fixed(total)\n\n\n" + TEST
PARKED = FIXED_HEAD + LOCAL + "\n\n" + CARRIED
DEAD_COPY = "if False:\n    def total(lines):\n        return 1\n\n\n"
# Both sides hold `def total` in front of `total = fixed(total)`. On the before side the definition
# makes the name local, so the assignment replaces nothing; each diff takes the definition out of the way.
DISPLACED = {
    "put_under_if_false": (PARKED, FIXED_HEAD + "if False:\n    def total(lines):\n        return 0\n\n\n" + CARRIED),
    "edited_and_put_under_if_false": (PARKED, FIXED_HEAD + DEAD_COPY + CARRIED),
    "moved_above_the_import": (PARKED, LOCAL + "\n\n" + FIXED_HEAD + CARRIED),
    "put_under_type_checking": (
        "from typing import TYPE_CHECKING\n" + PARKED,
        "from typing import TYPE_CHECKING\n" + FIXED_HEAD + "if TYPE_CHECKING:\n    def total(lines):\n        return 0\n\n\n" + CARRIED),
    "put_under_an_environment_branch": (
        "import os\n" + PARKED,
        "import os\n" + FIXED_HEAD + "if os.environ.get(\"LOCAL_TOTAL\"):\n    def total(lines):\n        return 0\n\n\n" + CARRIED),
    "moved_below_the_assignment_under_if_false": (
        PARKED, FIXED_HEAD + CARRIED.replace(TEST, "if False:\n    def total(lines):\n        return 0\n\n\n" + TEST)),
    # The diff only deletes the definition, in a file that keeps another definition of the name.
    "deleted_while_a_dead_copy_stays": (FIXED_HEAD + DEAD_COPY + LOCAL + "\n\n" + CARRIED, FIXED_HEAD + DEAD_COPY + CARRIED),
    "deleted_while_a_type_checking_stub_stays": (
        "from typing import TYPE_CHECKING\n" + FIXED_HEAD + "if TYPE_CHECKING:\n    def total(lines): ...\n\n\n" + LOCAL + "\n\n" + CARRIED,
        "from typing import TYPE_CHECKING\n" + FIXED_HEAD + "if TYPE_CHECKING:\n    def total(lines): ...\n\n\n" + CARRIED),
    # The definition stays; one line behind it puts production back under the name.
    "production_restored_behind_it": (
        "from app import prod\n" + PARKED, "from app import prod\n" + FIXED_HEAD + LOCAL + "\ntotal = prod.total\n\n\n" + CARRIED),
    "production_restored_under_an_environment_branch": (
        "import os\nfrom app import prod\n" + PARKED,
        "import os\nfrom app import prod\n" + FIXED_HEAD + LOCAL + "\nif not os.environ.get(\"LOCAL_TOTAL\"):\n    total = prod.total\n\n\n"
        + CARRIED),
}


@pytest.mark.parametrize("name", sorted(DISPLACED))
def test_a_stand_in_behind_a_displaced_definition_is_reported_as_on_the_release(name):
    """0.13.0 blocks each of these with this evidence. Read as an installation, the before side's
    definition made the assignment behind it look as if it had replaced production already."""
    before, after = DISPLACED[name]
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(target, text) for _path, _unit, target, text, _span in events] == [("app.prod.total", "total = fixed(total)")]


def test_a_stand_in_behind_a_definition_removed_inside_the_test_is_reported_as_on_the_release():
    """Here the definition installs while the test's body is followed, not while the module is loaded."""
    before = (IMPORT + "\n\ndef test_total():\n    def total(lines):\n        return 105.0\n\n"
              "    total = lambda lines: 105.0\n    assert total([(100, 1)]) == 105.0\n")
    after = before.replace("    def total(lines):\n        return 105.0\n\n", "")
    assert after != before
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [(target, text) for _path, _unit, target, text, _span in events] == [("app.prod.total", "total = lambda lines: 105.0")]


def test_the_released_reading_is_made_only_for_a_file_the_release_scheduled():
    """Both sides alias the name and rebind the alias; the diff only moves an old local definition above the import.

    0.13.0 does not schedule this file (nothing assigns to an imported name) and reports nothing. Read its way
    all the same, the second assignment would look new.
    """
    tail = "alias = total\nalias = lambda lines: 105.0\n\n\ndef test_total():\n    assert alias([(100, 1)]) == 105.0\n"
    before = IMPORT + "\n\n" + LOCAL + "\n\n" + tail
    after = LOCAL + "\n\n" + IMPORT + "\n\n" + tail
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


def test_a_conftest_stand_in_behind_a_displaced_definition_is_reported_as_on_the_release():
    head = "import pytest\nfrom app.prod import total\n\n\ndef fixed(function):\n    return lambda lines: 105.0\n\n\n"
    tail = "total = fixed(total)\n\n\n@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n"
    verdict, found = conftest_findings(head + "if False:\n    def total(lines):\n        return 0\n\n\n" + tail,
                                       head + LOCAL + "\n\n" + tail)
    assert verdict == "block"
    assert [row[:3] for row in found] == [("CONFTEST_PATCHES_PROD", "high", "tests/conftest.py")]


INNER = "    def total(lines):\n        return 105.0\n\n"
IN_HELPER = IMPORT + "\n\ndef computed():\n" + INNER + "    return total([(100, 1)])\n\n\ndef test_total():\n    assert computed() == 105.0\n"
IN_TEST = IMPORT + "\n\ndef test_total():\n" + INNER + "    assert total([(100, 1)]) == 105.0\n"
MOVED = {
    # The definition is the one the test already read through; the diff changes where it stands.
    "the_helper_around_it_is_renamed": (IN_HELPER, IN_HELPER.replace("computed", "priced")),
    "hoisted_out_of_the_test": (IN_TEST, SHADOWED + "\n\ndef test_other():\n    assert total([]) == 105.0\n"),
    "moved_into_the_only_test_that_uses_it": (SHADOWED, IN_TEST),
    "moved_from_a_helper_into_the_test": (
        IN_HELPER, IMPORT + "\n\ndef test_total():\n" + INNER + "    assert total([(100, 1)]) == 105.0\n"),
}


@pytest.mark.parametrize("name", sorted(MOVED))
def test_a_definition_the_test_already_read_through_is_not_new_where_it_moves(name):
    before, after = MOVED[name]
    assert before != after
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []


def test_a_definition_moved_into_the_test_s_reach_is_still_new():
    """The control for the moves above: on the before side no test read through the definition."""
    verdict, standins, _events = judged(UNUSED_HELPER, IN_TEST)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def judge_renamed(before, after):
    paths = sorted(before.keys() | after.keys())
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before[path].encode() if path in before else None, after[path].encode() if path in after else None)
               for path in paths if before.get(path) != after.get(path)]
    snapshot = {path: source.encode() for path, source in after.items()}
    _ir, findings, _verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 11, 20),
                                      root_reader=snapshot.get,
                                      root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                                      root_path_lister=lambda: sorted(snapshot),
                                      root_batch_reader=lambda wanted: {path: snapshot.get(path) for path in wanted})
    return [(f.unit, f.after.text if f.after else None) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]


CACHED = ("import functools\nfrom {module} import total\n\n\n_real = total\n\n\ndef total(lines):\n    return _real(tuple(lines))\n\n\n"
          "total = functools.lru_cache(maxsize=None)(total)\n\n\ndef test_total():\n    assert total(((100, 1),)) == 100\n")


def test_a_renamed_provider_under_an_untouched_definition_and_the_assignment_that_carries_it_on_is_not_new():
    """The module is renamed and the import follows; the wrapper and the `lru_cache` line are as they were."""
    def files(module):
        return {f"{module}.py": PRODUCTION, "tests/test_total.py": CACHED.format(module=module)}

    assert judge_renamed(files("billing"), files("invoicing")) == []


def test_an_import_moved_to_another_live_provider_under_an_untouched_definition_is_still_reported():
    """Not a rename: the old module is still there. The import's own row, which is 0.13.0's, is the finding."""
    def files(module):
        return {"money.py": MONEY, "pricing.py": MONEY,
                "tests/test_money.py": f"from {module} import Money\n\n\n" + SHADOW_CLASS + "\n\n" + MONEY_TEST}

    assert judge_renamed(files("money"), files("pricing")) == [("test_total", "from pricing import Money")]


def test_the_provider_a_definition_replaces_is_its_own_function_s_import_first():
    before = ("from app.prod import total\n\n\ndef test_total():\n    from app.other import total\n\n"
              "    assert total([(100, 1)]) == 105.0\n")
    after = ("from app.prod import total\n\n\ndef test_total():\n    def total(lines):\n        return 105.0\n\n"
             "    assert total([(100, 1)]) == 105.0\n")
    _verdict, _standins, events = judged(before, after, context={"src/app/other.py": PRODUCTION.encode()})
    assert [(target, text) for _path, _unit, target, text, _span in events] == [("app.other.total", "def total(lines):")]


def test_an_import_binds_a_name_to_its_last_alias():
    def target(source, name="total"):
        return _import_target(ast.parse(source).body[0], name)

    assert target("from app.prod import total\n") == "app.prod.total"
    assert target("from app.prod import total, other as total\n") == "app.prod.other"
    assert target("from app.prod import other as total, total\n") == "app.prod.total"
    assert target("from ..prod import total\n") == "..prod.total"
    assert target("import app.prod as total\n") == "app.prod"
    assert target("import app.prod\n", "app") == "app"
    assert target("from app.prod import other\n") is None


def test_settled_compares_what_each_binding_binds_the_name_to():
    def settled(before, after):
        return _settled(ast.parse(before), ast.parse(after))

    # The imported name and the relative level are part of what an import binds.
    assert settled(SHADOWED, SHADOWED.replace("import total", "import other as total")) == frozenset()
    assert settled(SHADOWED.replace("from app.prod", "from .prod"), SHADOWED.replace("from app.prod", "from prod")) == frozenset()
    assert settled(SHADOWED, SHADOWED.replace("import total", "import total, other as total")) == frozenset()
    # `typing.TYPE_CHECKING` is the same branch as `TYPE_CHECKING`: no run takes it.
    assert settled(SHADOWED, "import typing\n" + SHADOWED + "\n\nif typing.TYPE_CHECKING:\n    from app.types import total\n") == {
        ("", "total")}
    # A star import counts only in the definition's own scope.
    assert ("unused", "total") in settled(UNUSED_HELPER, UNUSED_HELPER + "\nfrom app.extra import *\n")
    # The same import statement in another scope is another binding.
    inside = "def helper():\n    from app.prod import total\n\n    def total(lines):\n        return 1\n\n    return total\n"
    outside = IMPORT + "\n\ndef helper():\n    def total(lines):\n        return 1\n\n    return total\n"
    assert ("helper", "total") not in settled(outside, inside)
    # A comprehension's loop variable is its own; a walrus in it binds in the scope around it.
    assert settled(SHADOWED, SHADOWED + "\nROWS = [total for total in (1, 2)]\n") == {("", "total")}
    assert settled(SHADOWED, SHADOWED + "\nROWS = [(total := 1) for _ in (1,)]\n") == frozenset()
    # A `for` binds the name to what its iterable yields.
    loop = SHADOWED + "\nfor total in [len]:\n    pass\n"
    assert settled(loop, loop) == {("", "total")}
    assert settled(loop, loop.replace("[len]", "[max]")) == frozenset()


def test_settled_tells_a_class_s_method_from_a_helper_s_definition_and_one_helper_from_another():
    method = IMPORT + "\n\nclass compute:\n    def total(lines):\n        return 105.0\n\n\n" + TEST
    nested = IMPORT + "\n\ndef compute():\n    def total(lines):\n        return 105.0\n\n\n" + TEST
    assert ("compute", "total") not in _settled(ast.parse(method), ast.parse(nested))
    assert ("compute", "total") in _settled(ast.parse(nested), ast.parse(nested))
    # A helper defined twice (an F811 name): the definition inside is settled
    # while every copy stays as it was, and not once one of them changes.
    twice = nested + "\n\ndef compute():\n    return None\n"
    assert ("compute", "total") in _settled(ast.parse(twice), ast.parse(twice))
    edited = twice.replace("    return None\n", "    return 0\n")
    assert ("compute", "total") not in _settled(ast.parse(twice), ast.parse(edited))
    live = twice.replace("\n\ndef compute():\n    return None\n", "\n\nif False:\n    def compute():\n        return None\n")
    assert ("compute", "total") not in _settled(ast.parse(twice), ast.parse(live))
    # The filter asks the same question.
    assert _definition_rebind(method.encode(), nested.encode(), set()) is True
    assert _definition_rebind(twice.encode(), (twice + "\n\nVALUE = 1\n").encode(), set()) is False


def test_a_class_namespace_turned_into_a_helper_is_reported():
    before = IMPORT + "\n\nclass compute:\n    def total(lines):\n        return 105.0\n\n\n" + TEST
    after = (IMPORT + "\n\ndef compute(lines):\n    def total(lines):\n        return 105.0\n\n    return total(lines)\n\n\n"
             "def test_total():\n    assert compute([(100, 1)]) == 105.0\n")
    verdict, standins, _events = judged(before, after)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_definition_s_identity_keeps_what_can_change_what_it_returns():
    def identity(source):
        return _definition_identity(ast.parse(source).body[0])

    # Text that looks like the empty `type_params` field, inside a string, stays.
    assert identity("def total(lines):\n    return 'a, type_params=[]'\n") != identity("def total(lines):\n    return 'a'\n")
    assert "type_params" not in identity("def total(lines):\n    return 1\n")
    # Nested definitions are normalised like the outer one.
    nested = "def total(lines):\n    def inner(x):\n        return x\n\n    return inner(1)\n"
    assert identity(nested.replace("def inner(x):\n", "def inner(x: int) -> int:\n        \"\"\"Words.\"\"\"\n")) == identity(nested)
    # Only a leading string is a docstring.
    assert identity("def total(lines):\n    x = 1\n    'note'\n    return x\n") != identity("def total(lines):\n    x = 1\n    return x\n")


def test_a_conftest_definition_s_digest_does_not_depend_on_the_interpreter_s_unicode_database():
    """U+1FA77 arrived with Unicode 15.0: CPython 3.11 writes it as an escape in the tree text and 3.12 as itself."""
    heart = "def total(lines):\n    return 105.0 if lines else \"\U0001FA77\"\n"
    assert _definition_digest(_definition_identity(ast.parse(heart).body[0])) == "d2906f60a85c"
    assert _definition_digest("definition:\u00e9") == _definition_digest("definition:\\xe9")
    _ir, findings, _verdict = judge_files({"tests/conftest.py": CONFTEST}, {"tests/conftest.py": conftest_with(heart)},
                                          {"tests/test_total.py": CONFTEST_TEST})
    assert [f.after.text for f in findings if f.rule == "CONFTEST_PATCHES_PROD"] == ["def total(lines):  # definition d2906f60a85c"]


def test_a_long_elif_chain_is_not_an_engine_error():
    """The filter reads every changed test file; a chain of 1,200 arms used to need 1,200 frames."""
    arms = "".join(f"    elif code == {index}:\n        return {index}\n" for index in range(1, 1200))
    helper = "def label(code):\n    if code == 0:\n        return 0\n" + arms + "    return -1\n"
    before = IMPORT + "\n\n" + helper + "\n\n" + TEST
    after = before.replace("    return -1\n", "    return -2\n")
    assert _definition_rebind(before.encode(), after.encode(), set()) is False
    assert _settled(ast.parse(before), ast.parse(after)) == frozenset()
    _verdict, standins, events = judged(before, after)
    assert standins == [] and events == []
    # A definition in one of the arms is found where it stands.
    shadow = before.replace("    elif code == 600:\n        return 600\n",
                            "    elif code == 600:\n        def total(lines):\n            return 105.0\n        return 600\n")
    assert shadow != before and _definition_rebind(before.encode(), shadow.encode(), set()) is False  # not a literal branch


def test_a_chain_of_aliases_is_judged_once_per_name():
    """Four names, each assigned sixty times from the next: the filter used to walk every path through them."""
    names = ["total", "second", "third", "fourth"]
    lines = ["fourth = len"]
    for left, right in zip(names, names[1:]):
        lines += [f"{left} = {right}"] * 60
    source = "\n".join(lines) + "\n\n\n" + DEF + "\n\n" + TEST
    assert _definition_rebind(None, source.encode(), set()) is False
    captured = source.replace("fourth = len", "from app import prod\nfourth = prod.total")
    assert _definition_rebind(None, captured.encode(), set()) is True


def test_the_alias_walk_is_judged_once_per_name_even_at_two_hundred_assignments():
    """Without the memo the walk takes seconds here (about 11 s on the author's machine); with it, milliseconds."""
    names = ["total", "second", "third", "fourth"]
    lines = ["fourth = len"]  # nothing captured: the walk has to try every path
    for left, right in zip(names, names[1:]):
        lines += [f"{left} = {right}"] * 200
    source = "\n".join(lines) + "\n\n\n" + DEF + "\n\n" + TEST
    started = time.perf_counter()
    assert _definition_rebind(None, source.encode(), set()) is False
    assert time.perf_counter() - started < 3.0


def test_the_alias_walk_remembers_each_name_at_its_own_depth():
    """`a` is five hops from the import, past the walk's limit; `c`, defined after it, is three.

    The walk for `a` meets `c` at depth 2 and `z` at depth 3 and gives up at
    `w`; the walk for `c` meets the same names nearer the import and must not
    take the earlier answers for them.
    """
    chain = "from app import prod\nw = prod.total\nz = w\nc = z\nb = c\na = b\n\n\n"
    defs = "def a(lines):\n    return 105.0\n\n\ndef c(lines):\n    return 105.0\n"
    assert _definition_rebind(chain.encode(), (chain + defs).encode(), set()) is True
    assert _definition_rebind(chain.encode(), (chain + defs.split("\n\n\ndef c")[0] + "\n").encode(), set()) is False


# Fifth review (#638). The fixture exemption reaches only what the test itself
# receives, and only the function the fixture's own body defines.

HANDED = "import pytest\n" + IMPORT + "\n\n@pytest.fixture\ndef fake_total():\n    {hand} total\n\n\n"
IN_BODY = "    def total(lines):\n        return 105.0\n\n"


@pytest.mark.parametrize("hand", ["return", "yield"])
def test_a_fixture_that_calls_another_fixture_s_handed_over_definition_is_reported(hand):
    consumer = ("@pytest.fixture\ndef amount(fake_total):\n    {hand} fake_total([(100, 1)])\n\n\n"
                "def test_total(amount):\n    assert amount == 105.0\n").format(hand=hand)
    before = HANDED.format(hand=hand) + consumer
    after = before.replace("def fake_total():\n", "def fake_total():\n" + IN_BODY)
    assert after != before
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


def test_a_fixture_that_passes_another_fixture_s_handed_over_definition_on_is_reported():
    before = (HANDED.format(hand="return") + "@pytest.fixture\ndef amount(fake_total):\n    return fake_total\n\n\n"
              "def test_total(amount):\n    assert amount([(100, 1)]) == 105.0\n")
    after = before.replace("def fake_total():\n", "def fake_total():\n" + IN_BODY)
    verdict, standins, _events = judged(before, after)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_conftest_fixture_that_calls_another_s_handed_over_definition_is_reported():
    before = ("import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef fake_total():\n    return total\n\n\n"
              "@pytest.fixture\ndef amount(fake_total):\n    return fake_total([(100, 1)])\n")
    after = before.replace("def fake_total():\n", "def fake_total():\n" + IN_BODY)
    verdict, found = conftest_findings(after, before)
    assert verdict == "block"
    assert [rule for rule, _severity, _path, _fingerprint in found] == ["CONFTEST_PATCHES_PROD"]


@pytest.mark.parametrize("hand_over", [
    "    total.result = total([(100, 1)])\n    return total.result\n",
    "    total.result = total([(100, 1)])\n    return getattr(total, 'result')\n",
])
def test_an_attribute_of_the_fixture_s_own_function_is_not_the_function(hand_over):
    """Only the bare function is handed over; an attribute holding its result is a use of it."""
    after = FIXTURE_HEAD + IN_BODY + hand_over + "\n\ndef test_total(amount):\n    assert amount == 105.0\n"
    verdict, standins, events = judged(FIXTURE_BEFORE, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


@pytest.mark.parametrize("before_class", ["", "    def total(lines):\n        return 0\n\n"])
def test_a_class_a_fixture_hands_the_test_is_reported(before_class):
    """A class keeps the name's earlier value, so it is never the fixture's handed-over function,
    even after a def of the same name in the same body."""
    test = "\n\ndef test_total(amount):\n    assert amount([(100, 1)]) == 105.0\n"
    before = FIXTURE_HEAD + "    return total\n" + test
    after = (FIXTURE_HEAD + before_class
             + "    class total(float):\n        def __new__(cls, lines):\n            return float.__new__(cls, 105.0)\n\n"
             + "    return total\n" + test)
    verdict, standins, events = judged(before, after)
    assert verdict == "block"
    assert standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert "class total(float):" in [text for _path, _unit, _target, text, _span in events]


def test_a_definition_a_fixture_yields_to_the_test_stays_with_the_fixture_passes():
    before = FIXTURE_HEAD + "    yield total\n\n\ndef test_total(amount):\n    assert amount([(100, 1)]) == 105.0\n"
    after = before.replace("def amount():\n", "def amount():\n" + IN_BODY)
    _verdict, _standins, events = judged(before, after)
    assert "def total(lines):" not in [text for _path, _unit, _target, text, _span in events]


def test_a_fixture_named_like_the_start_of_a_module_level_stand_in_hands_that_stand_in_on():
    """`@function:tot.` is not a prefix of `@function:total`: the fixture's own body defines nothing."""
    fixture = "@pytest.fixture\ndef tot():\n    return total\n\n\ndef test_total(tot):\n    assert tot([(100, 1)]) == 105.0\n"
    before = "import pytest\n" + IMPORT + "\n\n" + fixture
    after = "import pytest\n" + IMPORT + "\n\n" + DEF + "\n\n" + fixture
    verdict, standins, events = judged(before, after)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]
    assert [text for _path, _unit, _target, text, _span in events] == ["def total(lines):"]


# Fifth review (#638). A conftest that only the definition rule schedules, and
# that only kept its definitions or moved them at module level, does not bring
# in the refusals that 0.13.0 makes for a conftest it schedules over paths it
# never listed (an opaque directory pytest's collection reaches, an unsafe
# path). A file the run reads beneath it is read in full or stops the run.

MOVED_BEFORE = "import contextlib\nfrom app import prod\nfrom app.prod import total\n\n\ndef total(lines):\n    return prod.total(lines)\n"
MOVED_AFTER = ("import contextlib\nfrom app import prod\nfrom app.prod import total\n\n\n"
               "with contextlib.nullcontext():\n    def total(lines):\n        return prod.total(lines)\n")
NEW_AFTER = MOVED_BEFORE.replace("return prod.total(lines)", "return 105.0")


def judge_listed(before, after, unchanged, listed=()):
    """`judge_files` with extra entries in the path listing (a submodule as `dir/`, an unsafe name)."""
    common = {"app/__init__.py": b"", "app/prod.py": PRODUCTION.encode(), **unchanged}
    changes = [FileChange(path, "modified", before[path].encode(), after[path].encode())
               for path in sorted(after) if before[path] != after[path]]
    snapshot = {**common, **{path: source.encode() for path, source in after.items()}}
    listing = sorted(snapshot) + list(listed)
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 11, 21),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_path_lister=lambda: listing,
                   root_batch_reader=lambda paths: {path: snapshot.get(path) for path in paths})


TOTAL_TEST = IMPORT + "\n\n" + TEST


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
def test_a_conftest_definition_only_moved_brings_in_no_refusal(listed):
    before = {"conftest.py": MOVED_BEFORE, "tests/test_total.py": TOTAL_TEST}
    honest = {"conftest.py": MOVED_AFTER, "tests/test_total.py": TOTAL_TEST}
    _ir, findings, verdict = judge_listed(before, honest, {}, listed)
    assert verdict == "pass" and [f.rule for f in findings if f.severity in ("high", "critical")] == []
    # The same move beside a stand-in in a test file keeps 0.13.0's report.
    cheat = {"conftest.py": MOVED_AFTER, "tests/test_total.py": TOTAL_TEST.replace(
        "\n\ndef test_total", "\ntotal = lambda lines: 105.0\n\n\ndef test_total")}
    _ir, findings, verdict = judge_listed(before, cheat, {}, listed)
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"] == [
        ("TEST_PATCHES_SUBJECT", "total = lambda lines: 105.0")]


def test_a_file_over_a_limit_beneath_a_conftest_whose_definition_only_moved_stops_the_run():
    """The run does not skip what it cannot read: a stand-in brought out where
    it was parked could be read there."""
    before = {"conftest.py": MOVED_BEFORE, "tests/test_total.py": TOTAL_TEST}
    honest = {"conftest.py": MOVED_AFTER, "tests/test_total.py": TOTAL_TEST}
    big = {"tests/test_vectors.py": b"DATA = '" + b"x" * 1_000_001 + b"'\n\n\ndef test_vectors():\n    assert DATA\n"}
    with pytest.raises(EngineError, match="source byte limit"):
        judge_listed(before, honest, big)


def test_a_new_conftest_definition_above_a_submodule_pytest_reaches_still_stops_the_run():
    """What the submodule's tests read is unknown, as for a conftest 0.13.0 schedules."""
    before = {"conftest.py": MOVED_BEFORE, "tests/test_total.py": TOTAL_TEST}
    after = {"conftest.py": NEW_AFTER, "tests/test_total.py": TOTAL_TEST}
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed(before, after, {}, ["vendor/extlib/"])


PARKED = MOVED_BEFORE.replace("\n\ndef total(lines):\n    return prod.total(lines)\n",
                              "\n\nif False:\n    def total(lines):\n        return 105.0\n")
OUT_OF_PARKING = PARKED.replace("if False:\n    def total(lines):\n        return 105.0\n",
                                "def total(lines):\n    return 105.0\n")


def test_a_conftest_definition_brought_out_where_it_was_parked_is_new():
    """Only wrapped in a `with`, a definition reads as one the diff left alone;
    brought out of a dead branch, a class body or a function, it is bound
    another way, and the conftest refuses as for a new one."""
    def new(before, after):
        return _holds_new_definition(ast.parse(before), ast.parse(after))

    assert not new(MOVED_BEFORE, MOVED_AFTER)
    assert new(MOVED_BEFORE, NEW_AFTER)
    assert new(PARKED, OUT_OF_PARKING)
    helper = MOVED_BEFORE.replace("\n\ndef total(lines):\n    return prod.total(lines)\n",
                                  "\n\ndef helper():\n    def total(lines):\n        return prod.total(lines)\n")
    assert new(helper, MOVED_BEFORE)
    method = MOVED_BEFORE.replace("\n\ndef total(lines):\n    return prod.total(lines)\n",
                                  "\n\nclass Holder:\n    def total(lines):\n        return prod.total(lines)\n")
    assert new(method, MOVED_BEFORE)
    before = {"conftest.py": PARKED, "tests/test_total.py": TOTAL_TEST}
    after = {"conftest.py": OUT_OF_PARKING, "tests/test_total.py": TOTAL_TEST}
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed(before, after, {}, ["vendor/extlib/"])


# Fifth review (#638). Guards of the released reading, each pinned by a diff
# that a mutation of it gets wrong.

FLAGGED = {"app/__init__.py": b"", "app/prod.py": (PRODUCTION + "\nflag = False\n").encode()}
FIXED = "def fixed(function):\n    return lambda lines: 105.0\n"


def test_the_released_reading_keeps_a_stand_in_behind_a_definition_removed_in_a_conftest_fixture():
    """0.13.0 schedules the conftest for `prod.flag = True`; the copies of the conftest each test gets share the mark."""
    head = "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\nprod.flag = True\n\n\n@pytest.fixture\ndef amount():\n"
    tail = "    total = lambda lines: 105.0\n    return total([(100, 1)])\n"
    before = {"tests/conftest.py": head.replace("prod.flag = True\n\n\n", "") + "    def total(lines):\n        return 0\n\n" + tail}
    after = {"tests/conftest.py": head + tail}
    _ir, findings, verdict = judge_files(before, after, {**FLAGGED, "tests/test_total.py": CONFTEST_TEST})
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "CONFTEST_PATCHES_PROD"] == [
        ("CONFTEST_PATCHES_PROD", "total = lambda lines: 105.0")]


def test_the_released_reading_covers_the_tests_beneath_a_root_conftest():
    head = "import pytest\nfrom app.prod import total\n\n\n" + FIXED + "\n\n"
    tail = "total = fixed(total)\n\n\n@pytest.fixture\ndef amount():\n    return total([(100, 1)])\n"
    before = {"conftest.py": head + "def total(lines):\n    return 0\n\n\n" + tail}
    after = {"conftest.py": head + "if False:\n    def total(lines):\n        return 0\n\n\n" + tail}
    _ir, findings, verdict = judge_files(before, after, {**FLAGGED, "tests/test_total.py": CONFTEST_TEST})
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "CONFTEST_PATCHES_PROD"] == [
        ("CONFTEST_PATCHES_PROD", "total = fixed(total)")]


def test_two_rows_for_one_target_in_one_test_are_one_finding():
    before = ("from app import prod\n" + IMPORT + "\n\n" + FIXED + "\n\n"
              "def test_total():\n    assert total([(100, 1)]) == 105.0\n    assert prod.total([(100, 1)]) == 105.0\n")
    after = ("from app import prod\n" + IMPORT + "\n\n" + FIXED + "\n\ndef total(lines):\n    return 0\n\n\n"
             "total = fixed(total)\n\n\ndef test_total():\n    prod.total = lambda lines: 105.0\n"
             "    assert total([(100, 1)]) == 105.0\n    assert prod.total([(100, 1)]) == 105.0\n")
    _ir, findings, verdict = run(before, after, PRODUCTION)
    assert verdict == "block"
    fingerprints = [f.fingerprint for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert fingerprints and len(fingerprints) == len(set(fingerprints))


def test_a_moved_definition_beside_an_old_stand_in_reports_nothing():
    production = PRODUCTION + "\n\nrate = 0.0\n"
    before = ("from app import prod\n" + IMPORT + "\n\nprod.rate = 0.05\n\n\n"
              "def computed():\n    def total(lines):\n        return 105.0\n\n    return total([(100, 1)])\n\n\n"
              "def test_total():\n    assert computed() == 105.0\n    assert prod.rate == 0.05\n")
    verdict, standins, events = judged(before, before.replace("computed", "priced"), production)
    assert verdict == "pass" and standins == [] and events == []


def test_a_new_definition_on_a_target_with_an_old_attribute_stand_in_is_reported():
    test = ("def test_total():\n    prod.total = lambda lines: 105.0\n    assert prod.total([(100, 1)]) == 105.0\n"
            "    assert total([(100, 1)]) == 105.0\n")
    before = "from app import prod\n" + IMPORT + "\n\n" + test
    verdict, standins, events = judged(before, "from app import prod\n" + IMPORT + "\n\n" + DEF + "\n\n" + test)
    assert verdict == "block"
    assert "def total(lines):" in [text for _path, _unit, _target, text, _span in events]


def test_the_released_reading_counts_its_steps_apart(monkeypatch):
    """Each reading stays within the limit on its own; together they would not."""
    from checkwash.frontends.python import standin_installations

    def many(wrapped, scheduled):
        head = "import contextlib\n" + IMPORT + "\n\n"
        head += ("with contextlib.suppress(KeyError):\n    def total(lines):\n        return 105.0\n\n\n" if wrapped
                 else "def total(lines):\n    return 105.0\n\n\n")
        if scheduled:  # an attribute write 0.13.0 schedules the file for
            head += "class Box:\n    pass\n\n\nBox.x = 1\n\n\n"
        return head + "".join(f"def test_{i}():\n    assert total([(1, 1)]) == 105.0\n\n\n" for i in range(40))

    peaks = {}
    original = standin_installations._Trace._step

    def counted(self):
        original(self)
        peaks[id(self.budget)] = max(peaks.get(id(self.budget), 0), self.budget[0])

    monkeypatch.setattr(standin_installations._Trace, "_step", counted)
    judged(many(False, False), many(True, False))  # one reading: the file is not 0.13.0's
    one = max(peaks.values())
    monkeypatch.setattr(standin_installations._Trace, "_step", original)
    monkeypatch.setattr(standin_installations, "_MAX_ANALYSIS_STEPS", one * 3 // 2)
    verdict, _standins, _events = judged(many(False, True), many(True, True))  # both readings
    assert verdict == "pass"


@pytest.mark.parametrize("dead, live", [
    ("if True:\n    pass\nelif False:\n    pass\nelif True:\n", "if False:\n    pass\nelif False:\n    pass\nelif True:\n"),
    ("if True:\n    pass\nelif True:\n    pass\nelse:\n", "if False:\n    pass\nelif False:\n    pass\nelse:\n"),
])
def test_a_definition_in_a_later_arm_made_live_by_an_earlier_test_is_reported(dead, live):
    arm = "    def total(lines):\n        return 105.0\n"
    verdict, standins, _events = judged(IMPORT + "\n\n" + dead + arm + "\n\n" + TEST,
                                        IMPORT + "\n\n" + live + arm + "\n\n" + TEST)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


@pytest.mark.parametrize("comprehension", [
    "[total for total in (1, 2)]", "list(total for total in (1, 2))", "{total for total in (1, 2)}",
    "{total: 0 for total in (1, 2)}",
])
def test_a_comprehension_variable_beside_an_untouched_definition_binds_nothing(comprehension):
    shadowed = IMPORT + "\n\n" + DEF + "\n\n" + TEST
    after = shadowed + "\n\nROWS = " + comprehension + "\n"
    assert ("", "total") in _settled(ast.parse(shadowed), ast.parse(after))
    assert _definition_rebind(shadowed.encode(), after.encode(), set()) is False


# Fifth review (#638). Robustness.

def test_a_definition_the_trace_calls_may_hold_an_expression_deeper_than_the_stack():
    chain = " + ".join(["0"] * 1199 + ["105.0"])
    after = IMPORT + "\n\ndef total(lines):\n    return " + chain + "\n\n\n" + TEST
    verdict, standins, _events = judged(BEFORE, after)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


def test_a_test_folded_deeper_than_the_stack_is_not_an_engine_error():
    before = IMPORT + "\n\nFLAG = True\n\n\nif " + "not " * 1200 + "FLAG:\n    pass\n\n\n" + TEST
    after = before + "\n\ndef test_more():\n    assert total([(1, 1)]) == 1\n"
    assert _definition_rebind(before.encode(), after.encode(), set()) is False


# Sixth review (#638). A conftest stays lenient only where, from the first
# definition of a captured name in its scope on, the name is bound as the
# before side's last bindings there bind it, once a `with` or the taken branch
# of a literal `if` around a binding is set aside. A definition brought into
# force by a change from there on keeps the conftest strict, and a definition
# no capture reaches does not count.

SHADOW_FAKE = "def total(lines):\n    return 105.0\n"
SHADOW_FIXTURE = "\n\n@pytest.fixture\ndef amount():\n    return total\n"
SHADOW_READER = b"def test_total(amount):\n    assert amount([(100, 1)]) == 105.0\n"
BROUGHT_INTO_FORCE = {
    "import-moved-above": (
        "import pytest\n\n\n" + SHADOW_FAKE + "\n\nfrom app.prod import total\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app.prod import total\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    "later-definition-deleted": (
        "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n" + SHADOW_FAKE
        + "\n\ndef total(lines):\n    return prod.total(lines)\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    "restoring-import-made-dead": (
        "import pytest\nfrom app.prod import total\n\n\n" + SHADOW_FAKE
        + "\n\nif True:\n    from app.prod import total\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app.prod import total\n\n\n" + SHADOW_FAKE
        + "\n\nif False:\n    from app.prod import total\n" + SHADOW_FIXTURE),
    "restoring-assignment-deleted": (
        "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n" + SHADOW_FAKE
        + "\n\ntotal = prod.total\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    "del-and-reimport-deleted": (
        "import pytest\nfrom app.prod import total\n\n\n" + SHADOW_FAKE
        + "\n\ndel total\nfrom app.prod import total\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app.prod import total\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    "getattr-replaced-by-an-import-above": (
        "import pytest\nfrom app import prod\n\n\n" + SHADOW_FAKE + "\n\ntotal = getattr(prod, \"total\")\n"
        + SHADOW_FIXTURE,
        "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
}


@pytest.mark.parametrize("name", sorted(BROUGHT_INTO_FORCE))
def test_a_conftest_stand_in_brought_into_force_keeps_the_conftest_strict(name):
    """The stand-in was on the before side at module level, but a later
    binding of its name shadowed it. Readable, it is reported; beneath a
    submodule pytest reaches or beside a path holding `:`, the run stops."""
    before, after = BROUGHT_INTO_FORCE[name]
    assert _holds_new_definition(ast.parse(before), ast.parse(after))
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after},
                                          {"tests/test_total.py": SHADOW_READER})
    assert verdict == "block" and "CONFTEST_PATCHES_PROD" in {f.rule for f in findings}
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, {}, ["vendor/extlib/"])
    with pytest.raises(EngineError, match="unsafe path"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, {}, ["data/2024-01-01T00:00:00.json"])


HONEST_BEFORE = ("import contextlib\nimport pytest\nfrom app import prod\nfrom app.prod import total\n\n\n"
                 "def total(lines):\n    return prod.total(lines)\n")
HONEST_AFTER = HONEST_BEFORE.replace("def total(lines):\n    return prod.total(lines)\n",
                                     "with contextlib.nullcontext():\n    def total(lines):\n"
                                     "        return prod.total(lines)\n")
ROWS = "\n\n@pytest.fixture\ndef rows():\n    return [(1, 1)]\n"
HONEST_ALONGSIDE = {
    "an-unchanged-factory-fixture": (
        "\n\n@pytest.fixture\ndef make_lines():\n    def make(count):\n        return [(1, 1)] * count\n\n"
        "    return make\n",) * 2,
    "an-unchanged-method-holding-a-nested-def": (
        "\n\nclass Recorder:\n    def record(self, value):\n        def keep(item):\n            return item\n\n"
        "        return keep(value)\n",) * 2,
    "an-unrelated-fixture-edited": (ROWS, ROWS.replace("[(1, 1)]", "[(2, 1)]")),
    "an-unrelated-fixture-added": ("", ROWS),
    "an-unchanged-helper-holding-the-same-wrapper": (
        "\n\ndef helper():\n    def total(lines):\n        return prod.total(lines)\n\n    return total\n",) * 2,
    "an-unchanged-fixture-handing-over-a-definition-of-another-captured-name": (
        "\n\nfrom app.prod import rate\n\n\n@pytest.fixture\ndef discount():\n    def rate():\n        return 1.0\n\n"
        "    return rate\n",) * 2,
    "a-method-named-like-the-import-edited": (
        "\n\nclass Recorder:\n    def total(self, lines):\n        return 0\n",
        "\n\nclass Recorder:\n    def total(self, lines):\n        return 1\n"),
}


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
@pytest.mark.parametrize("name", sorted(HONEST_ALONGSIDE))
def test_an_honest_conftest_move_beside_other_definitions_brings_in_no_refusal(name, listed):
    """A conftest wrapper moved under `with`, beside definitions no capture
    reaches, definitions left alone, or another fixture edited or added."""
    extra_before, extra_after = HONEST_ALONGSIDE[name]
    before, after = HONEST_BEFORE + extra_before, HONEST_AFTER + extra_after
    assert not _holds_new_definition(ast.parse(before), ast.parse(after))
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": TOTAL_TEST}, {}, listed)
    assert verdict == "pass" and [f.rule for f in findings if f.severity in ("high", "critical")] == []


def test_an_edited_conftest_definition_of_a_captured_name_keeps_the_conftest_strict():
    after = HONEST_AFTER.replace("        return prod.total(lines)\n", "        return prod.total(lines) + 0\n")
    assert _holds_new_definition(ast.parse(HONEST_BEFORE), ast.parse(after))
    assert not _holds_new_definition(ast.parse(HONEST_BEFORE), ast.parse(HONEST_BEFORE.replace(
        "def total(lines):\n", "if True:\n    def total(lines):\n").replace(
        "    return prod.total(lines)\n", "        return prod.total(lines)\n")))
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed({"conftest.py": HONEST_BEFORE, "tests/test_total.py": TOTAL_TEST},
                     {"conftest.py": after, "tests/test_total.py": TOTAL_TEST}, {}, ["vendor/extlib/"])


COLON_READER = {"tests/run:2024/test_total.py": SHADOW_READER}
STRICT_BASE = "import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n    return total\n"


@pytest.mark.parametrize("install", ["def total(lines):\n    return 105.0\n", "total = lambda lines: 105.0\n"])
def test_a_reader_at_an_unsafe_path_beneath_a_strict_conftest_stops_the_run(install):
    """A new definition, or an assignment 0.13.0 schedules (and refuses there
    too), above a test whose path holds `:`."""
    after = STRICT_BASE.replace("\n\n\n@pytest", "\n\n\n" + install + "\n\n@pytest")
    with pytest.raises(EngineError, match="unsafe path"):
        judge_listed({"conftest.py": STRICT_BASE}, {"conftest.py": after}, COLON_READER)


TWICE_HELPERS = ("def _real():\n    return total([(100, 1)])\n\n\n"
                 "def helper():\n    return total([(100, 1)])\n\n\n"
                 "def helper():\n    def total(lines):\n        return 105.0\n\n    return total([(100, 1)])\n\n\n")
WITH_STAND_IN = "def helper():\n    def total(lines):\n        return 105.0\n\n    return total([(100, 1)])\n\n\n"
WITHOUT = "def helper():\n    return total([(100, 1)])\n\n\n"
HELPER_TEST = "def test_total():\n    assert helper() == 105.0\n"


@pytest.mark.parametrize("before, after", [
    (IMPORT + "\n\n" + TWICE_HELPERS + "helper = _real\n\n\n" + HELPER_TEST, IMPORT + "\n\n" + TWICE_HELPERS + HELPER_TEST),
    (IMPORT + "\n\n" + WITH_STAND_IN + WITHOUT + HELPER_TEST, IMPORT + "\n\n" + WITHOUT + WITH_STAND_IN + HELPER_TEST),
], ids=["shadowing-assignment-deleted", "copies-swapped"])
def test_a_stand_in_in_a_twice_defined_helper_brought_into_force_is_reported(before, after):
    """Every binding of a scope defined twice counts, in order, assignments too."""
    verdict, standins, _events = judged(before, after)
    assert verdict == "block" and standins


def test_a_test_s_nested_helper_that_binds_the_name_leaves_the_released_finding():
    """The trace's walk of a test's own bindings does not enter a function nested in it."""
    body = ("def test_total():\n    def helper():\n        total = 1\n        return total\n\n"
            "    assert total([(100, 1)]) == 105.0\n")
    verdict, standins, _events = judged(IMPORT + "\n\n" + body, IMPORT + "\ntotal = lambda lines: 105.0\n\n\n" + body)
    assert verdict == "block" and standins


@pytest.mark.parametrize("dead", ["from app.prod import total", "del total", "class total:\n            pass",
                                  "total = None"], ids=["import", "del", "class", "assignment"])
def test_a_name_the_test_binds_only_in_a_dead_branch_is_the_test_s_own(dead):
    """Python makes it local to the test wherever it is bound, so the test reads no stand-in."""
    body = "def test_total():\n    assert total([(100, 1)]) == 105.0\n    if False:\n        " + dead + "\n"
    verdict, standins, _events = judged(IMPORT + "\n\n" + body, IMPORT + "\ntotal = lambda lines: 105.0\n\n\n" + body)
    assert verdict == "pass" and standins == []


def test_a_scope_defined_twice_is_compared_once_for_the_definitions_inside_it():
    methods = "".join(f"    def test_{i}(self):\n        def total(lines):\n            return sum(p * q for p, q in lines)\n\n"
                      f"        assert total([(1, {i})]) == {i}\n\n" for i in range(150))
    klass = "class TestTotals:\n" + methods
    before = IMPORT + "\n\n" + klass + "\n\n" + klass + "\n\nVALUE = 1\n"
    started = time.perf_counter()
    assert len(_settled(ast.parse(before), ast.parse(before.replace("VALUE = 1", "VALUE = 2")))) == 150
    assert time.perf_counter() - started < 1.5


def test_an_added_conftest_holding_a_definition_of_a_captured_name_is_strict():
    assert _holds_new_definition(None, ast.parse(STRICT_BASE.replace("\n\n\n@pytest", "\n\n\n" + SHADOW_FAKE + "\n\n@pytest")))
    assert not _holds_new_definition(None, ast.parse(STRICT_BASE))


def test_a_definition_of_a_standard_library_name_does_not_keep_a_conftest_strict():
    """Only a capture of a first-party provider counts, as in the scheduling filter."""
    stdlib = "\n\nfrom json import dumps\n\n\ndef dumps(value):\n    return str(value)\n"
    before, after = HONEST_BEFORE + stdlib, HONEST_AFTER + stdlib.replace("str(value)", "repr(value)")
    assert _holds_new_definition(ast.parse(before), ast.parse(after))
    assert not _holds_new_definition(ast.parse(before), ast.parse(after), {"json"})
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": TOTAL_TEST}, {},
                                          ["vendor/extlib/"])
    assert verdict == "pass"


# Seventh review (#638). A change above a conftest's first definition of a
# captured name (the import a wrapper shadows deleted, renamed, moved under
# `if TYPE_CHECKING:` or pointed at another provider; a dead first copy
# deleted) changes only what the definition replaces: the conftest stays
# lenient. A change from the first definition on keeps it strict. Most pins
# below are diffs that one mutation of the comparison gets wrong.

PROVIDERS = {"app/prod.py": (PRODUCTION + "\n\ndef rate():\n    return 1.0\n").encode(),
             "app/pricing.py": PRODUCTION.encode()}
ABOVE = "import pytest\nfrom app import prod\nfrom app.prod import total\n\n\n"
WRAPPER = "def total(lines):\n    return prod.total(lines)\n"
TYPED = "from typing import TYPE_CHECKING\n\n" + ABOVE
BOTH = ABOVE.replace(IMPORT, "from app.prod import rate, total\n")
LEFT_ALONE = {
    "shadowed-import-deleted": (ABOVE + WRAPPER, ABOVE.replace(IMPORT, "") + WRAPPER),
    "shadowed-import-renamed": (ABOVE + WRAPPER, ABOVE.replace(IMPORT, "from app.prod import total as _total\n") + WRAPPER),
    "name-dropped-from-the-import-line": (BOTH + WRAPPER, ABOVE.replace(IMPORT, "from app.prod import rate\n") + WRAPPER),
    "shadowed-import-moved-under-type-checking": (
        TYPED + WRAPPER, TYPED.replace(IMPORT, "if TYPE_CHECKING:\n    " + IMPORT) + WRAPPER),
    "import-pointed-at-another-provider": (ABOVE + WRAPPER, ABOVE.replace("app.prod import", "app.pricing import") + WRAPPER),
    "dead-first-copy-deleted": (
        ABOVE + "def total(lines):\n    return sum(p * q for p, q in lines)\n\n\n" + WRAPPER, ABOVE + WRAPPER),
    "typing-only-import-added-below": (TYPED + WRAPPER, TYPED + WRAPPER + "\n\nif TYPE_CHECKING:\n    " + IMPORT),
    "wrapper-moved-into-the-else-of-a-dead-if": (
        ABOVE + WRAPPER, ABOVE + "if False:\n    pass\nelse:\n    def total(lines):\n        return prod.total(lines)\n"),
    "wrapper-moved-and-another-deleted": (
        BOTH + WRAPPER + "\n\ndef rate():\n    return prod.rate()\n",
        BOTH + "if True:\n    def total(lines):\n        return prod.total(lines)\n"),
    "wrapper-moved-and-a-name-added-to-the-import-below-it": (
        ABOVE.replace(IMPORT, "") + WRAPPER + "\n\n" + IMPORT,
        ABOVE.replace(IMPORT, "") + "if True:\n    def total(lines):\n        return prod.total(lines)\n\n\n"
        "from app.prod import rate, total\n"),
    # Eighth review (#638): bindings under `if TYPE_CHECKING:` are left out, nested or defined.
    "typing-only-import-nested-under-with-added-below-beside-the-f811-cleanup": (
        TYPED.replace("import pytest\n", "import contextlib\nimport pytest\n") + WRAPPER,
        TYPED.replace("import pytest\n", "import contextlib\nimport pytest\n").replace(IMPORT, "") + WRAPPER
        + "\n\nif TYPE_CHECKING:\n    with contextlib.nullcontext():\n        " + IMPORT),
    "typing-only-stub-added-below-beside-the-f811-cleanup": (
        TYPED + WRAPPER, TYPED.replace(IMPORT, "") + WRAPPER + "\n\nif TYPE_CHECKING:\n    def total(lines: list) -> float: ...\n"),
}


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
@pytest.mark.parametrize("name", sorted(LEFT_ALONE))
def test_a_conftest_wrapper_followed_by_what_followed_it_brings_in_no_refusal(name, listed):
    """Whatever reads `total` after the wrapper receives the same wrapper on both sides."""
    before, after = LEFT_ALONE[name]
    assert not _holds_new_definition(ast.parse(before), ast.parse(after))
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": TOTAL_TEST}, PROVIDERS, listed)
    assert verdict == "pass" and [f.rule for f in findings if f.severity in ("high", "critical")] == []


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
def test_a_conftest_import_cleanup_keeps_0130_s_report_elsewhere_in_the_diff(listed):
    """A strict conftest would stop the run, and 0.13.0's block of the test file's stand-in with it."""
    before, after = LEFT_ALONE["shadowed-import-deleted"]
    cheat = TOTAL_TEST.replace("\n\ndef test_total", "\ntotal = lambda lines: 105.0\n\n\ndef test_total")
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": cheat}, PROVIDERS, listed)
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"] == [
        ("TEST_PATCHES_SUBJECT", "total = lambda lines: 105.0")]


PARKED_HEAD = "import contextlib\nimport pytest\nfrom app import prod\nfrom app.prod import total\n\n\n"
LOCAL_FAKE = "import pytest\n\n\n@pytest.fixture\ndef amount():\n    def total(lines):\n        return 105.0\n\n"
TWICE_FIXTURE = ("import pytest\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n    return total\n\n\n"
                 "if {flag}:\n    @pytest.fixture\n    def amount():\n        def total(lines):\n            return 105.0\n\n"
                 "        return lambda lines: total(lines)\n")
INSTALLER = ("\n\n@pytest.fixture(autouse=True)\ndef install():\n{declared}    def total(lines):\n        return 105.0\n\n"
             "    yield\n")
FAKE_MODULE = {"app/fakes.py": b"def total(lines):\n    return 105.0\n"}
FAKES_HEAD = "import contextlib\nimport pytest\nfrom app import fakes, prod\nfrom app.prod import total\n\n\n"
SHIM = "try:\n    def total(lines):\n        return prod.total(lines)\nexcept Exception:\n    pass\n"
KEPT_STRICT = {
    "star-import-below-a-parked-stand-in-deleted": (
        PARKED_HEAD + SHADOW_FAKE + "\n\nfrom app.prod import *\n" + SHADOW_FIXTURE, PARKED_HEAD + SHADOW_FAKE + SHADOW_FIXTURE),
    "with-as-below-a-parked-stand-in-deleted": (
        PARKED_HEAD + SHADOW_FAKE + "\n\nwith contextlib.nullcontext(prod.total) as total:\n    pass\n" + SHADOW_FIXTURE,
        PARKED_HEAD + SHADOW_FAKE + SHADOW_FIXTURE),
    "only-import-below-a-parked-stand-in-deleted": (
        "import pytest\n\n\n" + SHADOW_FAKE + "\n\nfrom app.prod import total\n" + SHADOW_FIXTURE,
        "import pytest\n\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    "a-fixture-s-restoring-import-deleted": (
        LOCAL_FAKE + "    from app.prod import total\n    return lambda lines: total(lines)\n",
        LOCAL_FAKE + "    return lambda lines: total(lines)\n"),
    "dead-copy-of-a-twice-defined-fixture-made-live": (TWICE_FIXTURE.format(flag="False"), TWICE_FIXTURE.format(flag="True")),
    "global-added-in-a-fixture-holding-the-definition": (
        ABOVE + WRAPPER + INSTALLER.format(declared="") + SHADOW_FIXTURE,
        ABOVE + WRAPPER + INSTALLER.format(declared="    global total\n") + SHADOW_FIXTURE),
    # The fixture's wrapper overrode the module's stand-in when it ran; local, it no longer does.
    "global-removed-from-a-fixture-that-overrode-a-stand-in": (
        ABOVE + SHADOW_FAKE + INSTALLER.replace("return 105.0", "return prod.total(lines)").format(
            declared="    global total\n") + SHADOW_FIXTURE,
        ABOVE + SHADOW_FAKE + INSTALLER.replace("return 105.0", "return prod.total(lines)").format(declared="")
        + SHADOW_FIXTURE),
    "star-import-below-the-wrapper-pointed-elsewhere": (
        ABOVE + WRAPPER + "\n\nfrom app.prod import *\n" + SHADOW_FIXTURE,
        ABOVE + WRAPPER + "\n\nfrom app.fakes import *\n" + SHADOW_FIXTURE),
    "restoring-import-between-two-definitions-deleted": (
        ABOVE + SHADOW_FAKE + "\n\nfrom app.prod import total\ncalc = total\n\n\n" + WRAPPER
        + "\n\n@pytest.fixture\ndef amount():\n    return calc\n",
        ABOVE + SHADOW_FAKE + "\n\ncalc = total\n\n\n" + WRAPPER + "\n\n@pytest.fixture\ndef amount():\n    return calc\n"),
    # Eighth review (#638): each of these tells a surviving mutant of the comparison apart.
    "test-of-an-if-around-a-restoring-import-rewritten": (
        "import pytest\nfrom app.prod import total\n\nRESTORE = True\nSKIP = False\n\n\n" + SHADOW_FAKE
        + "\n\nif RESTORE:\n    from app.prod import total\n" + SHADOW_FIXTURE,
        "import pytest\nfrom app.prod import total\n\nRESTORE = True\nSKIP = False\n\n\n" + SHADOW_FAKE
        + "\n\nif SKIP:\n    from app.prod import total\n" + SHADOW_FIXTURE),
    "star-import-and-restore-swapped-on-one-line-beside-the-f811-cleanup": (
        FAKES_HEAD + SHADOW_FAKE + "\n\nfrom app.fakes import *; total = prod.total\n" + SHADOW_FIXTURE,
        FAKES_HEAD.replace(IMPORT, "") + SHADOW_FAKE + "\n\ntotal = prod.total; from app.fakes import *\n" + SHADOW_FIXTURE),
    "dead-copy-added-above-the-wrapper": (
        ABOVE + WRAPPER + SHADOW_FIXTURE,
        ABOVE + "if False:\n    def total(lines):\n        return sum(p * q for p, q in lines)\n\n\n" + WRAPPER + SHADOW_FIXTURE),
    "restoring-import-below-a-parked-stand-in-pointed-elsewhere": (
        FAKES_HEAD + SHADOW_FAKE + "\n\nfrom app.prod import total\n" + SHADOW_FIXTURE,
        FAKES_HEAD + SHADOW_FAKE + "\n\nfrom app.fakes import total\n" + SHADOW_FIXTURE),
    "restoring-assignment-below-a-parked-stand-in-respelled": (
        FAKES_HEAD.replace(IMPORT, "total = prod.total\n") + SHADOW_FAKE + "\n\ntotal = prod.total\n" + SHADOW_FIXTURE,
        FAKES_HEAD.replace(IMPORT, "total = prod.total\n") + SHADOW_FAKE + "\n\ntotal = fakes.total\n" + SHADOW_FIXTURE),
    "with-as-below-a-parked-stand-in-respelled": (
        FAKES_HEAD + SHADOW_FAKE + "\n\nwith contextlib.nullcontext(prod.total) as total:\n    pass\n" + SHADOW_FIXTURE,
        FAKES_HEAD + SHADOW_FAKE + "\n\nwith contextlib.nullcontext(fakes.total) as total:\n    pass\n" + SHADOW_FIXTURE),
    "stand-in-added-below-a-try-shim": (
        FAKES_HEAD + SHIM + SHADOW_FIXTURE, FAKES_HEAD + SHIM + "\n\n" + SHADOW_FAKE + SHADOW_FIXTURE),
    # A dead first copy makes the stand-in import a change below the first
    # definition, though it lies above the wrapper (red to green).
    "stand-in-import-between-a-dead-first-copy-and-the-wrapper": (
        FAKES_HEAD + "if False:\n    def total(lines):\n        return sum(p * q for p, q in lines)\n\n\ncalc = total\n\n\n"
        + WRAPPER + "\n\n@pytest.fixture\ndef amount():\n    return calc\n",
        FAKES_HEAD + "if False:\n    def total(lines):\n        return sum(p * q for p, q in lines)\n\n\n"
        "from app.fakes import total\ncalc = total\n\n\n" + WRAPPER + "\n\n@pytest.fixture\ndef amount():\n    return calc\n"),
}


@pytest.mark.parametrize("name", sorted(KEPT_STRICT))
def test_a_conftest_change_the_leniency_test_sees_keeps_it_strict(name):
    """From the first definition on, to the scopes around it, or to a `global` of the name."""
    before, after = KEPT_STRICT[name]
    assert _holds_new_definition(ast.parse(before), ast.parse(after))
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, {}, ["vendor/extlib/"])
    with pytest.raises(EngineError, match="unsafe path"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, {}, ["data/2024-01-01T00:00:00.json"])


@pytest.mark.parametrize("name", ["only-import-below-a-parked-stand-in-deleted",
                                  "restoring-import-below-a-parked-stand-in-pointed-elsewhere",
                                  "restoring-assignment-below-a-parked-stand-in-respelled", "stand-in-added-below-a-try-shim",
                                  "stand-in-import-between-a-dead-first-copy-and-the-wrapper"])
def test_a_stand_in_a_strict_conftest_brings_into_force_is_reported_where_its_reader_is_readable(name):
    """Among them, the import that captured the name on the before side only."""
    before, after = KEPT_STRICT[name]
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after},
                                          {**FAKE_MODULE, "tests/test_total.py": SHADOW_READER})
    assert verdict == "block" and "CONFTEST_PATCHES_PROD" in {f.rule for f in findings}


# Eighth review (#638). A `global` or `nonlocal` of the name makes a
# definition bind it in another scope when its function runs: there every
# binding of the name in that scope is compared, above the first definition
# too, and an unchanged one leaves the conftest lenient.

GLOBAL_DEFINITION = ("\n\ndef pytest_configure(config):\n    global {name}\n\n    def {name}({params}):\n"
                     "        return prod.{name}({params})\n")
WRAPPED = "if True:\n    def total(lines):\n        return prod.total(lines)\n"
UNCHANGED_GLOBAL = {
    "f811-cleanup-beside-a-global-definition-of-the-name": (
        ABOVE + WRAPPER + GLOBAL_DEFINITION.format(name="total", params="lines"),
        ABOVE.replace(IMPORT, "") + WRAPPER + GLOBAL_DEFINITION.format(name="total", params="lines")),
    "wrap-move-beside-a-global-definition-of-the-name": (
        ABOVE + WRAPPER + GLOBAL_DEFINITION.format(name="total", params="lines"),
        ABOVE + WRAPPED + GLOBAL_DEFINITION.format(name="total", params="lines")),
    "wrap-move-beside-a-global-definition-of-another-name": (
        BOTH + WRAPPER + GLOBAL_DEFINITION.format(name="rate", params=""),
        BOTH + WRAPPED + GLOBAL_DEFINITION.format(name="rate", params="")),
}


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
@pytest.mark.parametrize("name", sorted(UNCHANGED_GLOBAL))
def test_an_unchanged_global_definition_leaves_a_conftest_lenient(name, listed):
    before, after = UNCHANGED_GLOBAL[name]
    assert not _holds_new_definition(ast.parse(before), ast.parse(after))
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": TOTAL_TEST}, PROVIDERS, listed)
    assert verdict == "pass" and [f.rule for f in findings if f.severity in ("high", "critical")] == []


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
def test_a_wrap_move_beside_a_global_definition_keeps_0130_s_report_elsewhere_in_the_diff(listed):
    before, after = UNCHANGED_GLOBAL["wrap-move-beside-a-global-definition-of-another-name"]
    cheat = TOTAL_TEST.replace("\n\ndef test_total", "\ntotal = lambda lines: 105.0\n\n\ndef test_total")
    _ir, findings, verdict = judge_listed({"conftest.py": before, "tests/test_total.py": TOTAL_TEST},
                                          {"conftest.py": after, "tests/test_total.py": cheat}, PROVIDERS, listed)
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"] == [
        ("TEST_PATCHES_SUBJECT", "total = lambda lines: 105.0")]


# Eighth review (#638). What the leniency test does not see (D-215's
# Residuals): it matches the after side's bindings against the end of the
# before side's, and it does not look at what reads the name. Each of these
# conftests is lenient, so a test reading the stand-in from a submodule, or
# from a path holding `:`, is not read; where the test is readable, the
# stand-in is reported. The settled route to the same activation passes
# every engine, readable or not.

READ_CALC = "calc = total\n"
CALC_FIXTURE = "\n\n@pytest.fixture\ndef amount():\n    return calc\n"
SEEN_HEAD = "import pytest\n\nfrom app.prod import total\n\n\n"
EARLY_RETURN = ("import pytest\n\nfrom app import prod\nfrom app.prod import total\n\n\n@pytest.fixture\ndef amount():\n"
                "    return prod.total([(100, 1)])\n\n    def total(lines):\n        return 105.0\n\n"
                "    return total([(100, 1)])\n")
N4_TOP = "import contextlib\n\nimport pytest\n\nfrom app import prod\n"
N4_SOURCE = "\nSOURCE = prod.total\n"
N4_BEFORE = ("\n\ndef _fake_total():\n    global total\n    total = SOURCE\n\n    def total(lines):\n        return 105.0\n\n"
             "    return total\n")
N4_AFTER = ("\n\ndef _fake_total():\n    global total\n    total = SOURCE\n\n    with contextlib.nullcontext():\n"
            "        def total(lines):\n            return 105.0\n\n    return total\n")
N4_FIXTURE = "\n\n@pytest.fixture\ndef amount():\n    return _fake_total()\n"
NOT_SEEN = {
    # The ninth review's N4g and N4l: a name the function reads above the definition (`SOURCE`), unbound at the
    # base, so a run never reaches the definition, is bound at the head, beside a `with` put around the definition.
    "an-exception-before-a-global-definition-removed-by-binding-a-name-it-reads": (
        N4_TOP + N4_BEFORE + N4_FIXTURE, N4_TOP + N4_SOURCE + N4_AFTER + N4_FIXTURE),
    "an-exception-before-a-definition-removed-by-binding-a-name-it-reads": (
        N4_TOP + N4_BEFORE.replace("    global total\n", "") + N4_FIXTURE,
        N4_TOP + N4_SOURCE + N4_AFTER.replace("    global total\n", "") + N4_FIXTURE),
    "a-restoring-import-deleted-between-two-copies": (
        SEEN_HEAD + SHADOW_FAKE + "\n\nfrom app.prod import total\n" + READ_CALC + "\n\n" + SHADOW_FAKE + CALC_FIXTURE,
        SEEN_HEAD + SHADOW_FAKE + "\n\n" + READ_CALC + CALC_FIXTURE),
    "a-wrapper-deleted-between-two-copies": (
        SEEN_HEAD + SHADOW_FAKE + "\n\ndef total(lines):\n    return sum(p * q for p, q in lines)\n" + READ_CALC + "\n\n"
        + SHADOW_FAKE + CALC_FIXTURE,
        SEEN_HEAD + SHADOW_FAKE + "\n\n" + READ_CALC + CALC_FIXTURE),
    "a-reader-moved-beside-the-shadowed-import-deleted": (
        SEEN_HEAD + READ_CALC + "\n\n" + SHADOW_FAKE + CALC_FIXTURE,
        "import pytest\n\n\n" + SHADOW_FAKE + "\n\n" + READ_CALC + CALC_FIXTURE),
    "an-early-return-removed-beside-the-module-import-deleted": (
        EARLY_RETURN,
        EARLY_RETURN.replace("from app.prod import total\n", "").replace("    return prod.total([(100, 1)])\n\n", "")),
    # Ninth review (#638): in a fixture that declares the name `global`, a binding deleted in a scope around
    # (here the module's import) is not seen either.
    "an-early-return-removed-in-a-global-fixture-beside-the-module-import-deleted": (
        EARLY_RETURN.replace("def amount():\n", "def amount():\n    global total\n"),
        EARLY_RETURN.replace("def amount():\n", "def amount():\n    global total\n").replace(
            "from app.prod import total\n", "").replace("    return prod.total([(100, 1)])\n\n", "")),
}


@pytest.mark.parametrize("name", sorted(NOT_SEEN))
def test_what_the_leniency_test_does_not_see_is_reported_where_its_reader_is_readable(name):
    before, after = NOT_SEEN[name]
    assert not _holds_new_definition(ast.parse(before), ast.parse(after))
    reader = CONFTEST_TEST if name.startswith("an-early-return") else SHADOW_READER
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after}, {"tests/test_total.py": reader})
    assert verdict == "block" and "CONFTEST_PATCHES_PROD" in {f.rule for f in findings}


def test_a_star_import_counts_where_it_stands_among_a_scope_s_bindings():
    """A production star import moved above a parked stand-in brings the stand-in into force. The trace does
    not read what a star import binds, so nothing reports this diff, in either spelling; the comparison
    still orders the star import among the other bindings."""
    star = "from app.prod import *\n"
    before = ABOVE + WRAPPER + "\n\n" + DEF + "\n\n" + star
    after = ABOVE + WRAPPER + "\n\n" + star + "\n\n" + DEF
    assert _holds_new_definition(ast.parse(before), ast.parse(after))
    assert not _holds_new_definition(ast.parse(before), ast.parse(before))


SCOPE_BEFORE = ("import pytest\nfrom app import prod\nfrom app.prod import total\n\ntotal = lambda lines: 105.0\n"
                "from app.prod import total\n\n\n@pytest.fixture\ndef helper():\n    def total(lines):\n"
                "        return prod.total(lines)\n\n    return total\n\n\n@pytest.fixture\ndef amount():\n    return total\n")
SCOPE_AFTER = SCOPE_BEFORE.replace("total = lambda lines: 105.0\nfrom app.prod import total\n",
                                   "total = lambda lines: 105.0\n").replace(
    "def helper():\n    def total", "def helper():\n    from app.prod import total\n    def total")


def test_an_assignment_brought_into_force_beside_a_nested_wrapper_is_reported_where_its_reader_is_readable():
    """The stand-in is the module's `total = lambda`, brought into force by
    moving the import that restored production into a fixture. 0.13.0 does
    not report it, readable or not, and no version does when the fixture's
    wrapper is written as an assignment. The wrapper's scope binds `total`
    as before from the wrapper on, so the conftest is lenient: beneath a
    submodule the run passes, as on 0.13.0."""
    assert not _holds_new_definition(ast.parse(SCOPE_BEFORE), ast.parse(SCOPE_AFTER))
    _ir, findings, verdict = judge_listed({"conftest.py": SCOPE_BEFORE}, {"conftest.py": SCOPE_AFTER},
                                          {"tests/test_total.py": SHADOW_READER})
    assert verdict == "block"
    assert [(f.rule, f.after.text) for f in findings if f.rule == "CONFTEST_PATCHES_PROD"] == [
        ("CONFTEST_PATCHES_PROD", "total = lambda lines: 105.0")]
    _ir, _findings, verdict = judge_listed({"conftest.py": SCOPE_BEFORE}, {"conftest.py": SCOPE_AFTER}, {},
                                           ["vendor/extlib/"])
    assert verdict == "pass"


@pytest.mark.parametrize("alias", ["from app import prod\n\ntotal: object = prod.total\n",
                                   "import app.prod\n\ntotal = app.prod.total\n"], ids=["annotated", "two-attributes"])
def test_a_definition_after_an_alias_of_the_subject_is_reported(alias):
    verdict, standins, _events = judged(alias + "\n\n" + TEST, alias + "\n\n" + DEF + "\n\n" + TEST)
    assert verdict == "block" and standins == [("TEST_PATCHES_SUBJECT", "high", "test_total", MESSAGE)]


TWICE_DEFINED_HELPERS = (
    IMPORT + "\n\ndef first():\n    def total(lines):\n        return 1\n\n    return total\n\n\n"
    "def first():\n    def total(lines):\n        return 2\n\n    return total\n\n\n"
    "def helper():\n    return total\n\n\n"
    "if {flag}:\n    def helper():\n        def total(lines):\n            return 105.0\n\n        return total\n\n\n"
    "def test_total():\n    assert helper()([(100, 1)]) == 105.0\n")
TWICE_DEFINED_TESTS = (
    IMPORT + "\n\nclass TestA:\n    def test_x(self):\n        def total(lines):\n            return 1\n\n"
    "        assert total([(1, 1)]) == 1\n\n    def test_x(self):\n        def total(lines):\n            return 1\n\n"
    "        assert total([(1, 1)]) == 1\n\n\n"
    "class TestB:\n    def test_x(self):\n        assert total([(100, 1)]) == 105.0\n\n"
    "    if {flag}:\n        def test_x(self):\n            def total(lines):\n                return 105.0\n\n"
    "            assert total([(100, 1)]) == 105.0\n")


@pytest.mark.parametrize("source, unit", [(TWICE_DEFINED_HELPERS, "test_total"), (TWICE_DEFINED_TESTS, "TestB.test_x")],
                         ids=["helpers", "test-classes"])
def test_a_stand_in_made_live_in_the_second_of_two_scopes_defined_twice_is_reported(source, unit):
    """Each scope defined twice is compared on its own: the copies of the first say nothing about the second."""
    verdict, standins, _events = judged(source.format(flag="False"), source.format(flag="True"))
    assert verdict == "block" and [(rule, name) for rule, _severity, name, _message in standins] == [
        ("TEST_PATCHES_SUBJECT", unit)]


def test_a_conftest_holding_many_wrappers_of_one_name_judges_the_name_once(monkeypatch):
    copy = "def total(lines):\n    return prod.total(lines)\n\n\n"
    before = "from app import prod\nfrom app.prod import total\n\n\n" + copy * 2000
    after = "from app import prod\nfrom app.prod import total\n\n\nif True:\n" + "".join(
        "    " + line + "\n" if line else "\n" for line in (copy * 2000).splitlines())
    trees = ast.parse(before), ast.parse(after)
    judged, real = [], standin_installations._left_alone
    monkeypatch.setattr(standin_installations, "_left_alone",
                        lambda old, new, scope, name, memo: judged.append((scope, name)) or real(old, new, scope, name, memo))
    started = time.perf_counter()
    assert not _holds_new_definition(*trees)
    assert time.perf_counter() - started < 1.5
    assert judged == [("", "total")]


# Ninth review (#638). In a function holding a `global` or `nonlocal` of the
# name, every binding of it there counts, and in the scopes around it only
# deletions leave the conftest lenient: a binding added or changed there can be
# the provider the definition starts to replace, or what lets a run reach the
# definition at all (the function reads the name before it defines it). A
# declaration counts by its kind, under `if TYPE_CHECKING:` too and whatever
# else its line declares; one at module level declares nothing.

GLOBAL_TOP = "import pytest\nfrom app import prod\n"
GLOBAL_RESTORE = ("\n\n@pytest.fixture\ndef amount():\n    global total\n\n    def total(lines):\n        return 105.0\n\n"
                  "    from app.prod import total\n    return total([(100, 1)])\n")
GLOBAL_READ = ("\n\n@pytest.fixture\ndef amount():\n    global total\n    from app.prod import total\n    calc = total\n\n"
               "    def total(lines):\n        return prod.total(lines)\n\n    return calc([(100, 1)])\n")
GLOBAL_STAND_IN = ("\n\n@pytest.fixture\ndef amount():\n    global total\n\n    def total(lines):\n        return 105.0\n\n"
                   "    return total([(100, 1)])\n")
FORWARDING_COPY = "\n\n@pytest.fixture\ndef amount():\n    return prod.total([(100, 1)])\n"
NESTED_GLOBAL = ("\n\n@pytest.fixture\ndef amount():\n    total = prod.total\n\n    def inner():\n        global total\n\n"
                 "        def total(lines):\n            return 105.0\n\n    inner()\n    return total([(100, 1)])\n")
WRAPS_TOP = "import functools\n\nimport pytest\n"
WRAPS_HELPER = ("\n\ndef _fake_total():\n    global total\n\n    @functools.wraps(total)\n    def total(lines):\n"
                "        return 105.0\n\n    return total\n")
PLAIN_HELPER = "\n\ndef _fake_total():\n    global total\n\n    def total(lines):\n        return 105.0\n\n    return total\n"
NESTED_HELPER = ("\n\ndef _fake_total():\n    def _inner():\n        global total\n\n        @functools.wraps(total)\n"
                 "        def total(lines):\n            return 105.0\n\n        return total\n\n    return _inner()\n")
HELPER_FIXTURE = "\n\n@pytest.fixture\ndef amount():\n    return _fake_total()\n"
RESTORING_HELPER = "\n\ndef _restore():\n    global total\n    from app.prod import total\n"
RESTORED_STAND_IN = ("\n\n@pytest.fixture\ndef amount():\n    global total\n\n    def total(lines):\n        return 105.0\n\n"
                     "    _restore()\n    return total([(100, 1)])\n")
TC_TOP = "from typing import TYPE_CHECKING\n\nimport pytest\nfrom app import prod\n"
TC_REST = ("\n\ndef total(lines):\n    return prod.total(lines)\n\n\n@pytest.fixture\ndef amount():\n{declared}"
           "    def total(lines):\n        return 105.0\n\n    return 0\n\n\n@pytest.fixture\ndef result(amount):\n"
           "    return total([(100, 1)])\n")
TC_GLOBAL = "    if TYPE_CHECKING:\n        global total\n\n"
CONTEXT_TOP = "import contextlib\nimport functools\n\nimport pytest\nfrom app import prod\n"
WRAPPED_HELPER = ("\n\ndef _fake_total():\n    global total\n\n    with contextlib.nullcontext():\n        @functools.wraps(total)\n"
                  "        def total(lines):\n            return 105.0\n\n    return total\n")
TRY_FORWARDER = "\ntry:\n    def total(lines):\n        return prod.total(lines)\nexcept Exception:\n    pass\n"
OUTER_NONLOCAL = ("\n\ndef _fake_total():\n    def _inner():\n        nonlocal total\n\n        @functools.wraps(total)\n"
                  "        def total(lines):\n            return 105.0\n\n        return total\n\n{body}")
OUTER_GLOBAL = ("\n\ndef _fake_total():\n    {outer}\n\n    def _inner():\n        global total\n\n        def total(lines):\n"
                "            return 105.0\n\n        return total\n\n    return _inner()\n")
NESTED_NONLOCAL = ("\n\n@pytest.fixture\ndef amount():\n    total = prod.total\n{rate}\n    def inner():\n{declared}"
                   "        def total(lines):\n            return 105.0\n\n    inner()\n    return total\n")
HOLDER = ("\n\nclass Holder:\n{declared}    def method(self):\n        global total\n\n        def total(lines):\n"
          "            return prod.total(lines)\n\n        return total\n\n\n@pytest.fixture\ndef amount():\n    return total\n")
FORWARDER_FIXTURE = "\n\ndef total(lines):\n    return prod.total(lines)\n\n\n@pytest.fixture\ndef amount():\n    return total\n"
TWO_NAMES_TAIL = ("\n\ndef _fake_rate():\n    global rate\n\n    @functools.wraps(rate)\n    def rate():\n        return 2.0\n\n"
                  "    return rate\n\n\n@pytest.fixture\ndef amount():\n    return _fake_total()\n\n\n@pytest.fixture\n"
                  "def rate_fx():\n    return _fake_rate()\n")
GLOBAL_KEPT_STRICT = {
    "a-restoring-import-below-a-global-stand-in-deleted": (
        GLOBAL_TOP + GLOBAL_RESTORE, GLOBAL_TOP + GLOBAL_RESTORE.replace("    from app.prod import total\n", "")),
    "a-restoring-import-below-a-global-stand-in-pointed-at-a-fake": (
        GLOBAL_TOP + GLOBAL_RESTORE, GLOBAL_TOP + GLOBAL_RESTORE.replace("from app.prod", "from app.fakes")),
    "a-restoring-import-below-a-global-stand-in-made-dead": (
        GLOBAL_TOP + GLOBAL_RESTORE, GLOBAL_TOP + GLOBAL_RESTORE.replace(
            "    from app.prod import total\n", "    if False:\n        from app.prod import total\n")),
    "an-import-a-global-fixture-reads-above-its-wrapper-pointed-at-a-fake": (
        GLOBAL_TOP + GLOBAL_READ, GLOBAL_TOP + GLOBAL_READ.replace("from app.prod", "from app.fakes")),
    "the-forwarding-copy-of-a-twice-defined-global-fixture-deleted": (
        GLOBAL_TOP + IMPORT + GLOBAL_STAND_IN + FORWARDING_COPY, GLOBAL_TOP + IMPORT + GLOBAL_STAND_IN),
    "a-type-checking-global-fixture-s-import-pointed-at-a-fake": (
        "from typing import TYPE_CHECKING\n" + GLOBAL_TOP + GLOBAL_READ.replace("    global total\n", TC_GLOBAL),
        "from typing import TYPE_CHECKING\n" + GLOBAL_TOP
        + GLOBAL_READ.replace("    global total\n", TC_GLOBAL).replace("from app.prod", "from app.fakes")),
    "global-turned-into-nonlocal-in-a-nested-function": (
        GLOBAL_TOP + NESTED_GLOBAL, GLOBAL_TOP + NESTED_GLOBAL.replace("global total", "nonlocal total")),
    "nonlocal-added-in-a-nested-function": (
        GLOBAL_TOP + NESTED_GLOBAL.replace("        global total\n\n", ""),
        GLOBAL_TOP + NESTED_GLOBAL.replace("global total", "nonlocal total")),
    "a-module-import-added-beside-a-global-helper-that-reads-the-name-first": (
        WRAPS_TOP + WRAPS_HELPER + HELPER_FIXTURE, WRAPS_TOP + IMPORT + WRAPS_HELPER + HELPER_FIXTURE),
    # Honest (green at both commits), and priced: the import is the provider the definition starts to replace.
    "a-module-import-added-beside-a-global-helper": (
        WRAPS_TOP + PLAIN_HELPER + HELPER_FIXTURE, WRAPS_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE),
    "a-restore-through-global-elsewhere-deleted-beside-a-module-import-added": (
        "import pytest\n" + RESTORING_HELPER + RESTORED_STAND_IN,
        "import pytest\n" + IMPORT + RESTORING_HELPER.replace("    from app.prod import total\n", "") + RESTORED_STAND_IN),
    "a-type-checking-global-added-beside-the-f811-cleanup": (
        TC_TOP + IMPORT + TC_REST.format(declared=""), TC_TOP + TC_REST.format(declared=TC_GLOBAL)),
    "a-type-checking-global-added-alone": (
        TC_TOP + IMPORT + TC_REST.format(declared=""), TC_TOP + IMPORT + TC_REST.format(declared=TC_GLOBAL)),
    # Only deletions: two module-level bindings of the name swapped is a change.
    "two-module-bindings-of-the-name-swapped-beside-a-global-helper": (
        WRAPS_TOP + "from app import prod\n" + IMPORT + "total = prod.total\n" + WRAPS_HELPER + HELPER_FIXTURE,
        WRAPS_TOP + "from app import prod\ntotal = prod.total\n" + IMPORT + WRAPS_HELPER + HELPER_FIXTURE),
    # A binding around counts by what it binds the name to, not by its kind alone.
    "a-module-import-pointed-at-a-fake-beside-a-global-helper": (
        WRAPS_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE,
        WRAPS_TOP + IMPORT.replace("app.prod", "app.fakes") + PLAIN_HELPER + HELPER_FIXTURE),
    # A declaration's text is its kind's name, which an import of a module so named also gives.
    "a-global-declaration-replaced-by-an-import-of-a-module-named-global": (
        GLOBAL_TOP + IMPORT + GLOBAL_STAND_IN,
        GLOBAL_TOP + IMPORT + GLOBAL_STAND_IN.replace("    global total\n", "    import Global as total\n")),
    # Every scope around counts, not only the module or only the innermost.
    "a-module-import-added-beside-a-nested-global-helper": (
        WRAPS_TOP + NESTED_HELPER + HELPER_FIXTURE, WRAPS_TOP + IMPORT + NESTED_HELPER + HELPER_FIXTURE),
    "a-binding-of-the-name-changed-in-the-function-around-a-nonlocal-definition": (
        WRAPS_TOP + "\n\ndef _fake_total():\n    def _inner():\n        nonlocal total\n\n        def total(lines):\n"
        "            return 105.0\n\n        return total\n\n    total = None\n    return _inner()\n" + HELPER_FIXTURE,
        WRAPS_TOP + "\n\ndef _fake_total():\n    def _inner():\n        nonlocal total\n\n        if True:\n"
        "            def total(lines):\n                return 105.0\n\n        return total\n\n"
        "    from app.prod import total\n    return _inner()\n" + HELPER_FIXTURE),
    # The tenth review's distinguishing diffs: a scope around compares every kind of binding of the name, with its
    # compound statements and text, `nonlocal` as `global`, and class bodies too (code-v10-F1).
    "a-module-import-taken-out-of-a-dead-if-beside-a-global-helper-that-reads-the-name-first": (
        CONTEXT_TOP + "if False:\n    " + IMPORT + WRAPS_HELPER + HELPER_FIXTURE, CONTEXT_TOP + IMPORT + WRAPS_HELPER + HELPER_FIXTURE),
    "a-module-level-with-as-binding-added-after-a-del-beside-a-global-helper": (
        CONTEXT_TOP + IMPORT + "del total\n" + WRAPS_HELPER + HELPER_FIXTURE,
        CONTEXT_TOP + IMPORT + "del total\n\nwith contextlib.nullcontext(prod.total) as total:\n    pass\n" + WRAPS_HELPER
        + HELPER_FIXTURE),
    "a-module-level-star-import-added-after-a-del-beside-a-global-helper-whose-definition-is-wrapped": (
        CONTEXT_TOP + IMPORT + "del total\n" + WRAPS_HELPER + HELPER_FIXTURE,
        CONTEXT_TOP + IMPORT + "del total\nfrom app.prod import *\n" + WRAPPED_HELPER + HELPER_FIXTURE),
    "an-unreadable-module-level-forwarder-added-after-a-del-beside-a-global-helper": (
        CONTEXT_TOP + IMPORT + "del total\n" + WRAPS_HELPER + HELPER_FIXTURE,
        CONTEXT_TOP + IMPORT + "del total\n" + TRY_FORWARDER + WRAPS_HELPER + HELPER_FIXTURE),
    "a-type-checking-nonlocal-added-in-a-nested-function": (
        TC_TOP + NESTED_NONLOCAL.format(rate="", declared=""),
        TC_TOP + NESTED_NONLOCAL.format(rate="", declared="        if TYPE_CHECKING:\n            nonlocal total\n\n")),
    "a-declaration-around-a-nested-global-helper-replaced-by-an-import-of-a-module-named-global": (
        CONTEXT_TOP + IMPORT + OUTER_GLOBAL.format(outer="global total") + HELPER_FIXTURE,
        CONTEXT_TOP + IMPORT + OUTER_GLOBAL.format(outer="import Global as total") + HELPER_FIXTURE),
    "a-module-import-added-beside-a-nonlocal-helper-whose-outer-import-moved-above-its-call": (
        WRAPS_TOP + OUTER_NONLOCAL.format(body="    fake = _inner()\n    from app.prod import total\n    return fake\n")
        + HELPER_FIXTURE,
        WRAPS_TOP + IMPORT + OUTER_NONLOCAL.format(body="    from app.prod import total\n    fake = _inner()\n    return fake\n")
        + HELPER_FIXTURE),
    # The scopes around are compared once per scope and name, for each name on its own.
    "a-module-import-added-beside-the-second-of-two-global-helpers-of-different-names": (
        WRAPS_TOP + IMPORT + WRAPS_HELPER + TWO_NAMES_TAIL,
        WRAPS_TOP + IMPORT + "from app.prod import rate\n" + WRAPS_HELPER + TWO_NAMES_TAIL),
    # Honest (green at both commits), and priced: a class body around a method that declares the name `global` is
    # compared too, though a lone declaration there changes nothing a run or the trace reads.
    "a-no-op-global-added-to-a-class-body-around-a-global-method": (
        CONTEXT_TOP + IMPORT + HOLDER.format(declared=""), CONTEXT_TOP + IMPORT + HOLDER.format(declared="    global total\n\n")),
}


@pytest.mark.parametrize("name", sorted(GLOBAL_KEPT_STRICT))
def test_a_change_in_or_around_a_global_scope_keeps_the_conftest_strict(name):
    before, after = GLOBAL_KEPT_STRICT[name]
    assert _holds_new_definition(ast.parse(before), ast.parse(after))
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, FAKE_MODULE, ["vendor/extlib/"])
    with pytest.raises(EngineError, match="unsafe path"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, FAKE_MODULE, ["data/2024-01-01T00:00:00.json"])


@pytest.mark.parametrize("name, reader", [
    ("a-restoring-import-below-a-global-stand-in-deleted", CONFTEST_TEST),
    ("a-restoring-import-below-a-global-stand-in-pointed-at-a-fake", CONFTEST_TEST),
    ("a-restoring-import-below-a-global-stand-in-made-dead", CONFTEST_TEST),
    ("an-import-a-global-fixture-reads-above-its-wrapper-pointed-at-a-fake", CONFTEST_TEST),
    ("the-forwarding-copy-of-a-twice-defined-global-fixture-deleted", CONFTEST_TEST),
    ("a-type-checking-global-fixture-s-import-pointed-at-a-fake", CONFTEST_TEST),
    ("a-module-import-added-beside-a-global-helper-that-reads-the-name-first", SHADOW_READER),
    ("a-module-import-added-beside-a-global-helper", SHADOW_READER),
    ("a-module-import-added-beside-a-nested-global-helper", SHADOW_READER),
    ("a-restore-through-global-elsewhere-deleted-beside-a-module-import-added", CONFTEST_TEST),
    ("a-module-import-taken-out-of-a-dead-if-beside-a-global-helper-that-reads-the-name-first", SHADOW_READER),
    ("a-module-import-added-beside-a-nonlocal-helper-whose-outer-import-moved-above-its-call", SHADOW_READER),
])
def test_a_stand_in_a_strict_global_scope_brings_into_force_is_reported_where_its_reader_is_readable(name, reader):
    before, after = GLOBAL_KEPT_STRICT[name]
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after},
                                          {**FAKE_MODULE, "tests/test_total.py": reader})
    assert verdict == "block" and "CONFTEST_PATCHES_PROD" in {f.rule for f in findings}


def test_the_assignment_spelling_beside_a_global_helper_keeps_0130_s_refusal_and_report():
    """0.13.0 schedules the conftest for it, since the added import makes the assignment first-party."""
    helper = ("\n\ndef _fake_total():\n    global total\n    total = functools.wraps(total)(lambda lines: 105.0)\n"
              "    return total\n")
    before, after = WRAPS_TOP + helper + HELPER_FIXTURE, WRAPS_TOP + IMPORT + helper + HELPER_FIXTURE
    with pytest.raises(EngineError, match="vendor/extlib"):
        judge_listed({"conftest.py": before}, {"conftest.py": after}, {}, ["vendor/extlib/"])
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after},
                                          {"tests/test_total.py": SHADOW_READER})
    assert verdict == "block" and "CONFTEST_PATCHES_PROD" in {f.rule for f in findings}


GLOBAL_HOOK = "\n\ndef pytest_configure(config):\n    global {names}\n\n    def total(lines):\n        return prod.total(lines)\n"
DECLARED_TOP = "import typing\nfrom typing import TYPE_CHECKING\n\nimport pytest\nfrom app import prod\nfrom app.prod import rate, total\n"
DECLARED_HOOK = "\n\ndef pytest_configure(config):\n{declared}\n    def total(lines):\n        return prod.total(lines)\n"
TC_DECLARED = "    if TYPE_CHECKING:\n        global total\n"
GLOBAL_LENIENT = {
    # A `global` at module level declares nothing.
    "the-f811-cleanup-beside-a-module-level-global": (
        "global total\n" + GLOBAL_TOP + IMPORT + "\n\n" + WRAPPER + "\n\n@pytest.fixture\ndef amount():\n    return total\n",
        "global total\n" + GLOBAL_TOP + "\n\n" + WRAPPER + "\n\n@pytest.fixture\ndef amount():\n    return total\n"),
    # The enclosing function's `global` does not reach the nested one.
    "the-f811-cleanup-in-a-nested-function-beside-an-enclosing-global": (
        GLOBAL_TOP + "\n\n@pytest.fixture\ndef amount():\n    global total\n    total = prod.total\n\n    def inner():\n"
        "        from app.prod import total\n\n        def total(lines):\n            return prod.total(lines)\n\n"
        "        return total\n\n    return inner()\n",
        GLOBAL_TOP + "\n\n@pytest.fixture\ndef amount():\n    global total\n    total = prod.total\n\n    def inner():\n"
        "        def total(lines):\n            return prod.total(lines)\n\n        return total\n\n    return inner()\n"),
    "a-name-added-to-the-global-line": (
        BOTH + GLOBAL_HOOK.format(names="total"), BOTH + GLOBAL_HOOK.format(names="total, rate")),
    "the-global-line-split": (
        BOTH + GLOBAL_HOOK.format(names="rate, total"), BOTH + GLOBAL_HOOK.format(names="rate\n    global total")),
    # Around a function holding a `global` of the name, a binding of it deleted is no change.
    "the-module-import-deleted-beside-a-global-helper": (
        WRAPS_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE, WRAPS_TOP + PLAIN_HELPER + HELPER_FIXTURE),
    # A `global` at module level declares nothing: added beside a `global` helper it is no binding around it.
    "a-module-level-global-added-beside-a-global-helper": (
        WRAPS_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE, "global total\n" + WRAPS_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE),
    # A declaration applies to the whole function, whatever compound statement it is written in.
    "the-type-checking-guard-of-a-declaration-respelled": (
        DECLARED_TOP + DECLARED_HOOK.format(declared=TC_DECLARED),
        DECLARED_TOP + DECLARED_HOOK.format(declared=TC_DECLARED.replace("if TYPE_CHECKING:", "if typing.TYPE_CHECKING:"))),
    "a-declaration-moved-under-type-checking": (
        DECLARED_TOP + DECLARED_HOOK.format(declared="    global total\n"),
        DECLARED_TOP + DECLARED_HOOK.format(declared=TC_DECLARED)),
    # Around a function holding a `global` or `nonlocal` of the name, any bindings of it deleted, and a `nonlocal`
    # counted by its kind wherever it is written; a module-level `global` declares nothing under any statement.
    "the-last-of-two-module-bindings-deleted-beside-a-global-helper": (
        CONTEXT_TOP + IMPORT + "total = prod.total\n" + PLAIN_HELPER + HELPER_FIXTURE, CONTEXT_TOP + IMPORT + PLAIN_HELPER + HELPER_FIXTURE),
    "two-module-bindings-deleted-beside-a-global-helper": (
        CONTEXT_TOP + IMPORT + "total = prod.total\n" + PLAIN_HELPER + HELPER_FIXTURE, CONTEXT_TOP + PLAIN_HELPER + HELPER_FIXTURE),
    "a-nonlocal-moved-under-type-checking": (
        TC_TOP + NESTED_NONLOCAL.format(rate="", declared="        nonlocal total\n\n"),
        TC_TOP + NESTED_NONLOCAL.format(rate="", declared="        if TYPE_CHECKING:\n            nonlocal total\n\n")),
    "a-name-added-to-a-nonlocal-line": (
        TC_TOP + NESTED_NONLOCAL.format(rate="    rate = prod.rate\n", declared="        nonlocal total\n\n"),
        TC_TOP + NESTED_NONLOCAL.format(rate="    rate = prod.rate\n", declared="        nonlocal total, rate\n\n")),
    "the-f811-cleanup-beside-a-module-level-global-under-if-true": (
        "if True:\n    global total\n" + CONTEXT_TOP + IMPORT + FORWARDER_FIXTURE, "if True:\n    global total\n" + CONTEXT_TOP + FORWARDER_FIXTURE),
}


@pytest.mark.parametrize("listed", [["vendor/extlib/"], ["data/2024-01-01T00:00:00.json"]])
@pytest.mark.parametrize("name", sorted(GLOBAL_LENIENT))
def test_an_honest_change_beside_a_global_declaration_brings_in_no_refusal(name, listed):
    before, after = GLOBAL_LENIENT[name]
    assert not _holds_new_definition(ast.parse(before), ast.parse(after))
    _ir, findings, verdict = judge_listed({"conftest.py": before}, {"conftest.py": after}, PROVIDERS, listed)
    assert verdict == "pass" and [f.rule for f in findings if f.severity in ("high", "critical")] == []


def test_a_global_declaration_counts_by_its_kind_wherever_it_is_written():
    """The other names on its line, and the compound statement it is written in, do not unsettle a
    definition; one added under `if TYPE_CHECKING:` does."""
    for name in ("a-name-added-to-the-global-line", "the-global-line-split", "a-module-level-global-added-beside-a-global-helper",
                 "the-type-checking-guard-of-a-declaration-respelled", "a-declaration-moved-under-type-checking"):
        before, after = GLOBAL_LENIENT[name]
        assert _definition_rebind(before.encode(), after.encode(), set()) is False
    before, after = GLOBAL_KEPT_STRICT["a-type-checking-global-added-alone"]
    assert _definition_rebind(before.encode(), after.encode(), set()) is True
