"""A `with pytest.raises(...)` carrier earns D-179 relocation credit like an assert (D-192).

Outside report on #130 (comment 6531871133, 2026-10-30): two raises tests
folded into one literal parametrize blocked at high on 0.10.0, while 0.8.0
and 0.9.0 passed. D-179's Python proof bound only top-level `assert`
statements and stopped at the first `with`, so the carrier had no proof key.
The reviews of the fix found parametrize cells the proof read where the test
runs something else; those tests are here too, with the residual pins of
THREATMODEL row 179. These sources are parsed by CheckWash and never executed.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


TODAY = datetime.date(2026, 10, 31)
APP = b"def checked(x):\n    if not 0 <= x <= 100:\n        raise ValueError(x)\n    return x\n"
HEAD = "import pytest\nfrom app import checked\n\n\n"
NEGATIVE = '''def test_negative():
    with pytest.raises(ValueError):
        checked(-1)


'''
LARGE = '''def test_large():
    with pytest.raises(ValueError):
        checked(101)


'''
OK = '''def test_ok():
    assert checked(50) == 50
'''
VALID = '''

@pytest.mark.parametrize("ok", [50])
def test_valid(ok):
    assert checked(ok) == ok
'''
REPORTED_BEFORE = HEAD + NEGATIVE + LARGE + OK
REPORTED_AFTER = HEAD + '''@pytest.mark.parametrize("bad", [-1, 101])
def test_invalid(bad):
    with pytest.raises(ValueError):
        checked(bad)
''' + VALID


def check(before, after, *, freeze=False, snapshot=None):
    changes = [FileChange("test_app.py", "modified", before.encode(), after.encode())]
    sources = {"app.py": APP, **(snapshot or {})}
    return analyze(changes, Config(), Contract(oracle_freeze=freeze), [], TODAY,
                   root_reader=sources.get, root_searcher=lambda _: [])


def disabled(findings):
    return {f.unit: (f.severity, tuple(f.deescalators)) for f in findings if f.rule == "TEST_DISABLED"}


def test_reported_raises_fold_beside_an_equality_fold_passes():
    _ir, findings, verdict = check(REPORTED_BEFORE, REPORTED_AFTER)
    assert verdict == "pass"
    assert disabled(findings) == {
        "test_large": ("info", ("ASSERTION_MOVED",)),
        "test_negative": ("warn", ("RESTRUCTURED",)),
        "test_ok": ("warn", ("RESTRUCTURED",)),
    }


def test_pure_raises_fold_passes_without_any_strong_assertion():
    # Raises carriers without match= carry no D5 oracle mass. The file's lost
    # mass is zero, so D5 is a candidate and the proof decides.
    after = HEAD + '''@pytest.mark.parametrize("bad", [-1, 101])
def test_invalid(bad):
    with pytest.raises(ValueError):
        checked(bad)
'''
    _ir, findings, verdict = check(HEAD + NEGATIVE + LARGE, after)
    assert verdict == "pass"
    assert disabled(findings) == {
        "test_large": ("info", ("ASSERTION_MOVED",)),
        "test_negative": ("warn", ("RESTRUCTURED",)),
    }


def test_match_folded_into_a_literal_column_passes():
    before = HEAD + '''def test_negative():
    with pytest.raises(ValueError, match="-1"):
        checked(-1)


def test_large():
    with pytest.raises(ValueError, match="101"):
        checked(101)


''' + OK
    after = HEAD + '''@pytest.mark.parametrize("bad,msg", [(-1, "-1"), (101, "101")])
def test_invalid(bad, msg):
    with pytest.raises(ValueError, match=msg):
        checked(bad)
''' + VALID
    _ir, findings, verdict = check(before, after)
    assert verdict == "pass"
    assert {severity for severity, _ in disabled(findings).values()} == {"warn"}


def test_excinfo_assertion_after_the_carrier_is_proved_with_it():
    before = HEAD + '''def test_negative():
    with pytest.raises(ValueError) as excinfo:
        checked(-1)
    assert excinfo.value.args == (-1,)


def test_large():
    with pytest.raises(ValueError) as excinfo:
        checked(101)
    assert excinfo.value.args == (101,)
'''
    after = HEAD + '''@pytest.mark.parametrize("bad", [-1, 101])
def test_invalid(bad):
    with pytest.raises(ValueError) as excinfo:
        checked(bad)
    assert excinfo.value.args == (bad,)
'''
    _ir, findings, verdict = check(before, after)
    assert verdict == "pass"
    assert set(disabled(findings)) == {"test_negative", "test_large"}


@pytest.mark.parametrize("label,after", [
    ("exception broadened", REPORTED_AFTER.replace("pytest.raises(ValueError)", "pytest.raises(Exception)")),
    ("row dropped", REPORTED_AFTER.replace("[-1, 101]", "[-1]")),
    ("row changed", REPORTED_AFTER.replace("[-1, 101]", "[-1, 1000]")),
    ("raises swapped for warns", REPORTED_AFTER.replace("pytest.raises(ValueError)", "pytest.warns(UserWarning)")),
    ("subject call replaced", REPORTED_AFTER.replace("        checked(bad)", "        int(bad)")),
    ("statement that raises first", REPORTED_AFTER.replace("        checked(bad)", "        int('x')\n        checked(bad)")),
])
def test_a_weakened_raises_fold_still_blocks(label, after):
    _ir, findings, verdict = check(REPORTED_BEFORE, after)
    assert verdict == "block", label
    assert any(f.unit in {"test_negative", "test_large"} and f.severity == "high" for f in findings), label


def test_match_dropped_in_the_fold_still_blocks():
    before = HEAD + '''def test_negative():
    with pytest.raises(ValueError, match="-1"):
        checked(-1)


def test_large():
    with pytest.raises(ValueError, match="101"):
        checked(101)
'''
    after = HEAD + '''@pytest.mark.parametrize("bad", [-1, 101])
def test_invalid(bad):
    with pytest.raises(ValueError):
        checked(bad)
'''
    _ir, findings, verdict = check(before, after)
    assert verdict == "block"
    assert {severity for severity, _ in disabled(findings).values()} == {"high"}


@pytest.mark.parametrize("label,carrier", [
    ("a second item", "    with pytest.raises(ValueError), contextlib.nullcontext():\n        checked({})\n"),
    ("nested control flow", "    with pytest.raises(ValueError):\n        if True:\n            checked({})\n"),
])
def test_unsupported_raises_statements_stay_without_proof(label, carrier):
    # Honest, but outside the bounded carrier: no proof key, so no credit.
    head = "import contextlib\n" + HEAD
    before = (head + "def test_negative():\n" + carrier.format(-1) + "\n\n"
              + "def test_large():\n" + carrier.format(101))
    after = (head + '@pytest.mark.parametrize("bad", [-1, 101])\ndef test_invalid(bad):\n'
             + carrier.format("bad"))
    _ir, findings, verdict = check(before, after)
    assert verdict == "block", label


@pytest.mark.parametrize("decorator", [
    '@pytest.mark.parametrize("bad", [-1, 101], indirect=True)',
    '@pytest.mark.parametrize("bad", [-1, 101], indirect=["bad"])',
    '@pytest.mark.parametrize("bad", [-1, 101], True)',
    '@pytest.mark.parametrize("bad", [-1, 101], **{"indirect": True})',
])
def test_indirect_cells_are_not_substituted_into_a_raises_carrier(decorator):
    # The review of this change: the cells reach the fixture, which returns
    # 1000 for every row, so neither -1 nor 101 is checked any more. The
    # conftest names no `request`, so the startup context stays known.
    conftest = b"import pytest\n\n\n@pytest.fixture\ndef bad():\n    return 1000\n"
    after = REPORTED_AFTER.replace('@pytest.mark.parametrize("bad", [-1, 101])', decorator)
    _ir, findings, verdict = check(REPORTED_BEFORE, after, snapshot={"conftest.py": conftest})
    assert verdict == "block"
    assert {f.unit for f in findings if f.severity == "high"} == {"test_negative", "test_large"}


def test_indirect_cells_are_not_substituted_into_an_assert():
    # Older than raise carriers: D-179 read an indirect cell as the argument.
    conftest = b"import pytest\n\n\n@pytest.fixture\ndef ok():\n    return 7\n"
    after = HEAD + VALID.lstrip("\n").replace('[50])', '[50], indirect=True)')
    _ir, findings, verdict = check(HEAD + OK, after, snapshot={"conftest.py": conftest})
    assert verdict == "block"
    assert disabled(findings) == {"test_ok": ("high", ())}


@pytest.mark.parametrize("before_body,after_body", [
    # A dead binding the before side already had, then read as the cell.
    ("    bad = 1000\n    with pytest.raises(ValueError):\n        checked({})\n",
     "    bad = 1000\n    with pytest.raises(ValueError):\n        checked(bad)\n"),
    ("    with pytest.raises(ValueError):\n        bad = 1000\n        checked({})\n",
     "    with pytest.raises(ValueError):\n        bad = 1000\n        checked(bad)\n"),
    # `as` binds the ExceptionInfo before the block runs: checked(<ExceptionInfo>).
    ("    with pytest.raises(ValueError) as bad:\n        checked({})\n",
     "    with pytest.raises(ValueError) as bad:\n        checked(bad)\n"),
    # A parameter is a binding too, though not a Name: the lambda reads 1000.
    ("    with pytest.raises(ValueError):\n        checked((lambda bad: {})(1000))\n",
     "    with pytest.raises(ValueError):\n        checked((lambda bad: bad)(1000))\n"),
], ids=["prefix", "block", "as target", "lambda parameter"])
def test_a_column_rebound_in_the_body_is_not_its_cell(before_body, after_body):
    before = (HEAD + "def test_negative():\n" + before_body.format(-1) + "\n\n"
              + "def test_large():\n" + before_body.format(101) + "\n\n" + OK)
    after = HEAD + '@pytest.mark.parametrize("bad", [-1, 101])\ndef test_invalid(bad):\n' + after_body + VALID
    _ir, findings, verdict = check(before, after)
    assert verdict == "block"
    assert {f.unit for f in findings if f.severity == "high"} == {"test_negative", "test_large"}


def test_a_column_rebound_before_an_assert_is_not_its_cell():
    # Older than raise carriers: the assert read 7 at run time and 50 in its key.
    before = HEAD + "def test_ok():\n    ok = 7\n    assert checked(50) == 50\n"
    after = HEAD + '@pytest.mark.parametrize("ok", [50])\ndef test_valid(ok):\n    ok = 7\n    assert checked(ok) == ok\n'
    _ir, findings, verdict = check(before, after)
    assert verdict == "block"
    assert disabled(findings) == {"test_ok": ("high", ())}


@pytest.mark.parametrize("marks", [
    "pytest.mark.xfail(run=False, strict=True)",
    'pytest.mark.skipif("sys.version_info >= (3,)", reason="slow")',
    'pytest.mark.skip.with_args(reason="slow")',
    "pytest.mark.slow",
])
def test_a_row_with_marks_that_may_keep_it_from_running_proves_nothing(marks):
    after = REPORTED_AFTER.replace("[-1, 101]", "[pytest.param(-1, marks=%s), 101]" % marks)
    _ir, findings, verdict = check(REPORTED_BEFORE, after)
    assert verdict == "block", marks
    assert {f.unit for f in findings if f.severity == "high"} == {"test_negative", "test_large"}, marks


def test_a_row_with_marks_before_an_assert_proves_nothing():
    # Older than raise carriers: an xfail(run=False) row never runs.
    after = HEAD + VALID.lstrip("\n").replace("[50]", "[pytest.param(50, marks=pytest.mark.xfail(run=False, strict=True))]")
    _ir, findings, verdict = check(HEAD + OK, after)
    assert verdict == "block"
    assert disabled(findings) == {"test_ok": ("high", ())}


def test_a_row_proved_skipped_is_left_out_and_the_rest_still_prove():
    after = REPORTED_AFTER.replace("[-1, 101]", "[-1, 101, pytest.param(7, marks=pytest.mark.skip)]")
    _ir, findings, verdict = check(REPORTED_BEFORE, after)
    assert verdict == "pass"
    assert {severity for severity, _ in disabled(findings).values()} <= {"info", "warn"}


def test_a_sync_test_moved_into_async_def_proves_nothing():
    # Raised by Argon, verified by Claude: a plain TestCase never awaits an
    # async test method, so its assertion never runs and the test passes.
    before = HEAD.replace("import pytest\n", "import unittest\n") + (
        "class T(unittest.TestCase):\n    def test_ok(self):\n        assert checked(50) == 50\n")
    after = before.replace("    def test_ok(self):", "    async def test_ok_renamed(self):")
    _ir, findings, verdict = check(before, after)
    assert verdict == "block"
    assert disabled(findings) == {"T.test_ok": ("high", ())}


@pytest.mark.parametrize("before_kind,after_kind,verdict", [
    ("def", "async def", "block"),
    ("async def", "async def", "pass"),
])
def test_a_raises_fold_keeps_its_function_kind(before_kind, after_kind, verdict):
    before = (HEAD + NEGATIVE + LARGE).replace("def test_", before_kind + " test_")
    after = REPORTED_AFTER.replace(VALID, "\n").replace("def test_invalid", after_kind + " test_invalid")
    _ir, findings, actual = check(before, after)
    assert actual == verdict


def test_a_mutable_cell_read_twice_is_one_object_not_two_literals():
    # Raised by Argon, verified by Claude: the after side compares the sorted
    # list with itself, a tautology; the before side failed on a correct sort.
    app = b"def sort_in_place(xs):\n    xs.sort()\n    return xs\n\n\ndef total(xs):\n    return sum(xs)\n"
    head = "import pytest\nfrom app import sort_in_place, total\n\n\n"
    before = head + "def test_sort():\n    assert sort_in_place([2, 1]) == [2, 1]\n"
    after = head + '@pytest.mark.parametrize("xs", [[2, 1]])\ndef test_sort_rows(xs):\n    assert sort_in_place(xs) == xs\n'
    _ir, findings, verdict = check(before, after, snapshot={"app.py": app})
    assert verdict == "block"
    assert disabled(findings) == {"test_sort": ("high", ())}
    # Read once, the cell is the literal it replaced.
    before = head + "def test_total():\n    assert total([1, 2]) == 3\n"
    after = head + '@pytest.mark.parametrize("xs", [[1, 2]])\ndef test_total_rows(xs):\n    assert total(xs) == 3\n'
    _ir, findings, verdict = check(before, after, snapshot={"app.py": app})
    assert verdict == "pass"


def test_residual_row179_a_row_a_configured_k_filter_deselects_still_pays():
    # Open, older than D-192: the proof does not read the configured selection,
    # so pytest deselects the 101 row ("2 passed, 1 deselected") while it pays
    # for test_large. A fix changes this expectation as a recorded change.
    ini = b'[pytest]\naddopts = -k "not slowcase"\n'
    after = REPORTED_AFTER.replace("[-1, 101]", '[-1, pytest.param(101, id="slowcase")]')
    _ir, findings, verdict = check(REPORTED_BEFORE, after, snapshot={"pytest.ini": ini})
    assert verdict == "pass"
    assert disabled(findings)["test_large"][0] != "high"


@pytest.mark.parametrize("arrival,snapshot", [
    ("app_test.py", {"pytest.ini": b"[pytest]\npython_files = test_*.py\n"}),
    ("test_legacy.py", {"conftest.py": b'collect_ignore = ["test_legacy.py"]\n'}),
], ids=["python_files", "collect_ignore"])
def test_residual_row179_a_test_moved_where_pytest_never_collects_still_pays(arrival, snapshot):
    # Open, older than D-192: arrival liveness reads pytest's default patterns,
    # not the repository's own collection settings, so a test moved unchanged
    # into a file pytest never runs still earns the complete-unit move credit.
    changes = [FileChange("test_app.py", "modified", (HEAD + NEGATIVE + OK).encode(), (HEAD + NEGATIVE).encode()),
               FileChange(arrival, "added", None, (HEAD + OK).encode())]
    sources = {"app.py": APP, **snapshot}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=sources.get, root_searcher=lambda _: [])
    assert verdict == "pass"
    assert disabled(findings) == {"test_ok": ("info", ("ASSERTION_MOVED",))}


def test_a_zero_mass_fold_into_another_file_is_a_move_not_a_restructure():
    # D5 takes a file that lost no mass only when a live unit arrived in it too;
    # the text route moves one raises test, and the other still blocks.
    changes = [FileChange("test_app.py", "modified", (HEAD + NEGATIVE + LARGE + OK).encode(), (HEAD + OK).encode()),
               FileChange("test_invalid.py", "added", None, REPORTED_AFTER.replace(VALID, "\n").encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader={"app.py": APP}.get, root_searcher=lambda _: [])
    assert verdict == "block"
    assert sorted(severity for severity, _ in disabled(findings).values()) == ["high", "info"]


def test_oracle_freeze_still_raises_assertion_only_credit_to_high():
    _ir, findings, verdict = check(REPORTED_BEFORE, REPORTED_AFTER, freeze=True)
    assert verdict == "block"
    frozen = [f for f in findings if "ORACLE_FREEZE" in f.escalators]
    assert frozen and all(f.severity == "high" for f in frozen)
