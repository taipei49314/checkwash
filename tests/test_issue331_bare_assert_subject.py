"""Issue #331: a bare `assert`'s subject is compared before "polarity inverted".

ASSERT_WEAKENED calls a flipped polarity an inversion only when the subject
is otherwise unchanged (SPEC §4), and it compared subjects by `left`. The
Python frontend records no subject for a bare truthy or `isinstance` assert,
nor for a `pytest.approx` comparison, so `left` was None on both sides and
every such pair read as one subject: click `7360097e` respelled `assert
result.okay` as `assert not result.exception` four times, and each read
"assertion polarity inverted ... the test now proves the opposite".

What each statement checks is now compared instead: the tested expression
with its `not`s peeled, or the side of an approx comparison that is not the
approx call. The verdict does not move: a replaced assertion still blocks
without repair evidence.
"""
import datetime
import warnings

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.assert_weakened import _checks_another_subject
from checkwash.engine import analyze
from checkwash.ir import strength as S
from checkwash.ir.astutil import asserted_subject
from checkwash.ir.model import Assertion

HEADER = "import unittest\n\nimport pytest\n\nfrom app.cli import other, ready, result, stopped\n"
INVERTED = "assertion polarity inverted ({}) — the test now proves the opposite"
REPLACED = ("assertion replaced — subject and polarity both changed ({} -> {}); "
            "checkwash cannot verify the replacement is equivalent")


def _source(line):
    if line.startswith("self."):
        return (HEADER + "\n\nclass TestCli(unittest.TestCase):\n    def test_cli(self):\n"
                + "".join(f"        {part}\n" for part in line.split("\n")))
    return HEADER + "\n\ndef test_cli():\n" + "".join(f"    {part}\n" for part in line.split("\n"))


def judge(before, after):
    changes = [FileChange("tests/test_cli.py", "modified", _source(before).encode(), _source(after).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7))
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


def replaced(before, after):
    return ("block", [("ASSERT_WEAKENED", "high", REPLACED.format(before, after))])


def inverted(direction="positive -> negative"):
    return ("block", [("ASSERT_WEAKENED", "high", INVERTED.format(direction))])


# --- the issue's rows ---------------------------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    ("assert result.okay", "assert not result.exception"),
    ("assert result.okay", "assert not other.failed"),
    ("assert ready()", "assert not stopped()"),
    ("assert x == 1", "assert y != 1"),
    ("self.assertTrue(result.okay)", "self.assertFalse(result.exception)"),
], ids=["attribute", "another_object", "another_call", "control_comparison", "control_assert_true"])
def test_another_subject_with_its_polarity_flipped_is_a_replacement(before, after):
    assert judge(before, after) == replaced(before, after)


def test_the_same_subject_with_its_polarity_flipped_is_an_inversion():
    assert judge("assert result.okay", "assert not result.okay") == inverted()


# --- what a bare assert checks ------------------------------------------------------------------

@pytest.mark.parametrize("before, after, direction", [
    ("assert not result.okay", "assert result.okay", "negative -> positive"),
    ("assert result.okay", "assert not (result.okay)", "positive -> negative"),
    ("assert (\n    result.okay\n)", "assert not result.okay", "positive -> negative"),
    ("assert not not result.okay", "assert not result.okay", "positive -> negative"),
    ("assert result.okay, 'ok'", "assert not result.okay, 'not ok'", "positive -> negative"),
    ("assert isinstance(result, int)", "assert not isinstance(result, int)", "positive -> negative"),
], ids=["negative_to_positive", "parentheses", "over_lines", "double_negation", "message", "isinstance"])
def test_a_respelled_subject_is_the_same_subject(before, after, direction):
    assert judge(before, after) == inverted(direction)


@pytest.mark.parametrize("before, after", [
    ("assert not result.okay", "assert other.okay"),
    ("assert result.okay, 'ok'", "assert not result.exception, 'ok'"),
    ("assert isinstance(result, int)", "assert not isinstance(other, int)"),
    ("assert isinstance(result, int)", "assert not isinstance(result, str)"),
], ids=["negative_to_positive", "message", "isinstance_another_object", "isinstance_another_type"])
def test_another_checked_expression_is_a_replacement(before, after):
    assert judge(before, after) == replaced(before, after)


@pytest.mark.parametrize("statement, subject", [
    ("assert result.okay", "result.okay"),
    ("assert not result.okay", "result.okay"),
    ("assert not not result.okay", "result.okay"),
    ("assert result.okay, 'message'", "result.okay"),
    ("assert (\n        result.okay\n    )", "result.okay"),
    ("    assert result.okay\n", "result.okay"),
    ("assert isinstance(result, int)", "isinstance(result, int)"),
    ("assert total() == pytest.approx(78.75)", "total()"),
    ("assert approx(78.75, abs=0.01) != total()", "total()"),
    ("assert not total() == approx(78.75)", "total()"),
    ("assert approx(1) == approx(2)", "approx(1) == approx(2)"),
    ("assert approx(0) <= total() <= 5", "approx(0) <= total() <= 5"),
    ("assert total() == approximately(78.75)", "total() == approximately(78.75)"),
    ("assert total() == 78.75", "total() == 78.75"),
    ("x = 1", None),
    ("assert x\nassert y", None),
    ("expect(total()).toBe(78.75)", None),
    ("assert (", None),
], ids=["bare", "negated", "double_negation", "message", "over_lines", "indented", "isinstance", "approx",
        "approx_on_the_left", "negated_approx", "two_approx_calls", "chained", "another_name", "comparison",
        "not_an_assert", "two_statements", "javascript", "unparseable"])
def test_what_an_assert_statement_checks(statement, subject):
    assert asserted_subject(statement) == subject


def test_reading_a_statement_again_adds_no_warning():
    """The file warned when it was read; its statement read again stays quiet (#319)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert asserted_subject("assert re.match('\\d+', s)") == "re.match('\\\\d+', s)"
    assert caught == []


# --- where the statement decides ----------------------------------------------------------------

def _record(text, form, positive, left=None):
    return Assertion(id=text, form=form, strength=S.APPROX if form == "approx" else S.TRUTHY, text=text,
                     span=(1, 1), left=left, positive=positive)


@pytest.mark.parametrize("path, before, after, another", [
    # An approx comparison records no subject either; the side that is not
    # the approx call decides (#284 reads `!=` and `not` as negated).
    ("tests/test_cli.py", _record("assert total() == pytest.approx(78.75)", "approx", True),
     _record("assert other() != pytest.approx(78.75)", "approx", False), True),
    ("tests/test_cli.py", _record("assert total() == pytest.approx(78.75)", "approx", True),
     _record("assert total() != pytest.approx(78.75)", "approx", False), False),
    # Only when neither side records a subject, and only in Python: `left`
    # decides the rest, as before.
    ("tests/test_cli.py", _record("assert x == 1", "compare_eq", True, left="x"),
     _record("assert not result.okay", "truthy", False), False),
    ("tests/test_cli.py", _record("assert result.okay", "truthy", True),
     _record("assert x != 1", "compare_eq", False, left="x"), False),
    ("tests/cli.test.js", _record("assert(ok)", "truthy", True), _record("assert(other)", "truthy", False), False),
    # A text that is no `assert` statement leaves `left` to decide.
    ("tests/test_cli.py", _record("assert result.okay", "truthy", True),
     _record("pytest.fail()", "truthy", False), False),
], ids=["approx_another_subject", "approx_same_subject", "before_records_a_subject", "after_records_a_subject",
        "javascript", "not_an_assert"])
def test_when_the_statement_decides(path, before, after, another):
    assert _checks_another_subject(path, before, after) is another
