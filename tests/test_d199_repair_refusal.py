"""D-199 (0.12): which findings refuse repair evidence, and which routes stay open.

Each test pins one sentence of SPEC §5's "Rules that take no repair evidence"
paragraph, or of THREATMODEL item 4 and rows 56, 93, 130 and 131.
`tests/test_issue419_residual.py` pins the four unit-scoped weakening rules;
this file pins the other refused rules, the JS/TS split, the removal shapes
and the open routes the D-199 review found. A test named `test_open_...`
pins a documented open route: a fix changes it, as a recorded change.

All input programs are source data, not runtime-qualified repair examples.
"""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping

TODAY = datetime.date(2026, 11, 6)
REFUSED = ("high", [], ["REPAIR_EVIDENCE_REFUSED"], "block")
HELD = ("warn", ["REPAIR_EVIDENCE"], [], "pass")
TEMPLATE = FileChange("app/templates/invoice.html", "modified",
                      b"<p>{{ total }}</p>\n", b"<!-- c -->\n<p>{{ total }}</p>\n")


def run(changes, **kwargs):
    return analyze(list(changes), Config(), Contract(), [], TODAY, **kwargs)


def one(changes, rule, **kwargs):
    """(severity, de-escalators, escalators, verdict) of the one finding of `rule`."""
    _ir, findings, verdict = run(changes, **kwargs)
    hit, = [f for f in findings if f.rule == rule]
    return hit.severity, hit.deescalators, hit.escalators, verdict


# --- Python: the stand-in and subject rules refuse too --------------------------------------------

STAND_IN_BEFORE = (b"from app import billing\n\n\n"
                   b"def test_invoice_total(monkeypatch):\n"
                   b"    items = [10.0, 90.0]\n"
                   b"    assert billing.invoice_total(items, 0.053) == 105.3\n")
STAND_IN_AFTER = STAND_IN_BEFORE.replace(
    b"    items = [10.0, 90.0]\n",
    b"    monkeypatch.setattr(billing, \"invoice_total\", lambda *a: 105.3)\n    items = [10.0, 90.0]\n")


def test_a_python_stand_in_refuses_repair_evidence():
    # The inputs of `test_patches_subject_pos`, beside a template comment.
    change = FileChange("tests/test_billing.py", "modified", STAND_IN_BEFORE, STAND_IN_AFTER)
    assert one([change, TEMPLATE], "TEST_PATCHES_SUBJECT") == REFUSED


DERIVED_BEFORE = (b"from billing import invoice_total\n\n\n"
                  b"def test_invoice_total_applies_tax():\n"
                  b"    items = [50.0, 50.0]\n"
                  b"    assert invoice_total(items, 0.05) == 105.0\n")
DERIVED_AFTER = DERIVED_BEFORE.replace(
    b"    assert invoice_total(items, 0.05) == 105.0\n",
    b"    expected = sum(items)\n    assert invoice_total(items, 0.05) == expected\n")


def test_a_python_derived_expectation_refuses_repair_evidence():
    # The inputs of `expectation_derived_pos`, beside a template comment.
    change = FileChange("tests/test_billing.py", "modified", DERIVED_BEFORE, DERIVED_AFTER)
    assert one([change, TEMPLATE], "EXPECTED_VALUE_DERIVED") == REFUSED


# --- Python: the routes that stay open ------------------------------------------------------------

CALC = b"def compute(x):\n    return x * 2\n"
CALC_NOOP = b"def compute(x):\n    return x * 2 + 0\n"
CALC_TEST = b"from app.calc import compute\n\n\ndef test_compute():\n    assert compute(2) == 4\n"


def _calc(test_after, calc_after=CALC_NOOP):
    return [FileChange("app/__init__.py", "unchanged", b"", b""),
            FileChange("tests/test_calc.py", "modified", CALC_TEST, test_after),
            FileChange("app/calc.py", "modified", CALC, calc_after)]


def test_open_a_weakening_respelled_as_an_exact_comparison():
    """A weakening written as an exact comparison reads as an expected value changed (D-199 review).

    `assert compute(2) > 0` is ASSERT_WEAKENED and refuses repair evidence;
    `assert (compute(2) > 0) == True` reads as EXPECTED_VALUE_CHANGED, 4 to
    True, which keeps it, so a `+ 0` in the called function holds it at
    warn (THREATMODEL 130). A fix of the expected-value detector changes
    this expectation, as a recorded change.
    """
    direct = CALC_TEST.replace(b"compute(2) == 4", b"compute(2) > 0")
    respelled = CALC_TEST.replace(b"compute(2) == 4", b"(compute(2) > 0) == True")
    assert one(_calc(direct), "ASSERT_WEAKENED") == REFUSED
    assert one(_calc(respelled), "EXPECTED_VALUE_CHANGED") == HELD


def test_open_an_expectation_computed_through_a_module_alias():
    """An expectation computed from the subject through a module alias keeps the credit (D-199 review).

    `expected = compute(2)` is EXPECTED_VALUE_DERIVED and refuses repair
    evidence; `calc.compute(2)` reads as EXPECTATION_DEFINITION_CHANGED,
    which keeps it (THREATMODEL 130). A fix changes this expectation, as a
    recorded change.
    """
    aliased = CALC_TEST.replace(b"from app.calc import compute\n", b"from app.calc import compute\nfrom app import calc\n")
    aliased = aliased.replace(b"== 4", b"== calc.compute(2)")
    local = CALC_TEST.replace(b"    assert compute(2) == 4\n", b"    expected = compute(2)\n    assert compute(2) == expected\n")
    # The alias resolves only against the repository's files, as in a real run.
    for test_after, rule, outcome in ((aliased, "EXPECTATION_DEFINITION_CHANGED", HELD),
                                      (local, "EXPECTED_VALUE_DERIVED", REFUSED)):
        root = {"app/__init__.py": b"", "app/calc.py": CALC_NOOP, "tests/test_calc.py": test_after}
        assert one(_calc(test_after), rule, root_reader=root.get, root_searcher=lambda needles: []) == outcome


FMT = b"def _fmt(x):\n    return str(x)\n\n\ndef render(x):\n    return _fmt(x)\n"
FMT_TEST = (b"from app.fmt import _fmt, render\n\n\n"
            b"def test_fmt():\n    assert _fmt(3) == \"3\"\n\n\n"
            b"def test_render():\n    assert render(3) == \"3\"\n")


def test_open_a_renamed_private_symbol_escorts_a_test_deletion_into_d8():
    # THREATMODEL 56: a rename is a deletion to D8, so a rename that changes
    # no behaviour holds the deleted test at warn.
    renamed = FMT.replace(b"_fmt", b"_format")
    test_after = FMT_TEST.replace(b"_fmt, render", b"render").replace(
        b"def test_fmt():\n    assert _fmt(3) == \"3\"\n\n\n", b"")
    changes = [FileChange("app/__init__.py", "unchanged", b"", b""),
               FileChange("app/fmt.py", "modified", FMT, renamed),
               FileChange("tests/test_fmt.py", "modified", FMT_TEST, test_after)]
    assert one(changes, "TEST_DISABLED") == ("warn", ["PROD_SYMBOL_REMOVED"], [], "pass")


ROWS = (b"import pytest\n\nfrom app.fmt import render\n\n\n"
        b"@pytest.mark.parametrize(\"n\", [1, 2])\n"
        b"def test_render(n):\n    assert render(n) == str(n)\n")


def test_a_row_marked_off_is_no_removal_for_d8():
    # A row marked off with `pytest.param(..., marks=skip)` stays written
    # down: it is an in-place disable, not a deleted row, so D8 does not
    # hold it beside a removed symbol (SPEC §5 D8 and D-199).
    marked = ROWS.replace(b"[1, 2]", b"[1, pytest.param(2, marks=pytest.mark.skip)]")
    changes = [FileChange("app/__init__.py", "unchanged", b"", b""),
               FileChange("app/fmt.py", "modified", FMT, FMT.replace(b"_fmt", b"_format")),
               FileChange("tests/test_render.py", "modified", ROWS, marked)]
    severity, deescalators, _escalators, verdict = one(changes, "TEST_DISABLED")
    assert (severity, deescalators, verdict) == ("high", [], "block")


# --- the removal shapes after the second review ----------------------------------------------------

def _render(test_before, test_after):
    """`render`'s test beside a renamed private `_fmt`: a removed symbol the test file reaches (D8)."""
    return [FileChange("app/__init__.py", "unchanged", b"", b""),
            FileChange("app/fmt.py", "modified", FMT, FMT.replace(b"_fmt", b"_format")),
            FileChange("tests/test_render.py", "modified", test_before, test_after)]


def test_rows_deleted_beside_a_row_marked_off_are_no_removal_for_d8():
    # The finding carries both events, so D8 held the marked-off row on the
    # deleted one's back (D-199 second review).
    before = ROWS.replace(b"[1, 2]", b"[1, 2, 3, 4]")
    after = ROWS.replace(b"[1, 2]", b"[1, 2, pytest.param(3, marks=pytest.mark.skip)]")
    _ir, findings, verdict = run(_render(before, after))
    hit, = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert "1 disabled, 1 deleted" in hit.message
    assert (hit.severity, hit.deescalators, verdict) == ("high", [], "block")


def test_a_table_emptied_where_it_stands_is_no_removal():
    # A test whose table lost every row still stands and runs nothing: an
    # in-place disable, for D8 in Python and for the split in JS/TS.
    severity, deescalators, _escalators, verdict = one(_render(ROWS, ROWS.replace(b"[1, 2]", b"[]")), "TEST_DISABLED")
    assert (severity, deescalators, verdict) == ("high", [], "block")
    before = JS_HEAD + TABLE
    assert one(_js(before, JS_HEAD + TABLE.replace(b"[[1], [2], [3]]", b"[]")), "TEST_DISABLED") == REFUSED


DOUBLE = b"def double(x):\n    return x + x\n\n\ndef triple(x):\n    return 3 * x\n"
DOUBLE_TEST = b"from app.prod import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
DOUBLE_WRAPPED = (b"import pytest\n\nfrom app.prod import double\n\n\n"
                  b"@pytest.mark.parametrize(\"_unused\", [])\n"
                  b"def test_double(_unused):\n    assert double(2) == 4\n")


def test_a_python_test_wrapped_in_an_empty_parameter_set_is_no_removal_for_d8():
    # The proof that a parameter set is empty gives the plain side a count
    # of one, so it read as a table that lost its row, and D8 held it beside
    # the removed `triple` (D-199 second review).
    head = {"src/app/__init__.py": b"", "src/app/prod.py": b"def double(x):\n    return x + x - 1\n",
            "tests/test_case.py": DOUBLE_WRAPPED}
    changes = [FileChange("tests/test_case.py", "modified", DOUBLE_TEST, DOUBLE_WRAPPED),
               FileChange("src/app/prod.py", "modified", DOUBLE, head["src/app/prod.py"])]
    def search(needles):
        return search_source_mapping(head, needles)

    _ir, findings, verdict = run(changes, known_modules={"app", "pytest"}, self_modules={"app"},
                                 head_reader=head.get, head_searcher=search, root_reader=head.get,
                                 root_searcher=search)
    hit, = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert hit.message == "test_double: 1 parametrized case(s) deleted (1 -> 0)"
    assert (hit.severity, hit.deescalators, hit.escalators, verdict) == REFUSED


STRICT = (b"import pytest\n\nfrom app.fmt import render\n\nSTRICT = True\n\n\n"
          b"@pytest.mark.parametrize(\"n\", [1, 2, 3])\n"
          b"def test_render(n):\n    if not STRICT:\n        pytest.skip(\"lenient\")\n    assert render(n) == str(n)\n")


def test_only_the_lost_rows_are_a_removal_for_d8():
    # A skip guard made always true on a unit that also lost rows: D8 holds
    # the rows, not the guard (D-199 second review; the shape decides).
    lenient = STRICT.replace(b"STRICT = True", b"STRICT = False").replace(b"[1, 2, 3]", b"[1]")
    _ir, findings, verdict = run(_render(STRICT, lenient))
    by_shape = {f.shape: (f.severity, f.deescalators) for f in findings if f.rule == "TEST_DISABLED"}
    assert by_shape == {"guard_weakened": ("high", []), "param_cases_removed": ("warn", ["PROD_SYMBOL_REMOVED"])}
    assert verdict == "block"


def test_open_a_row_marked_off_in_rows_that_cannot_be_paired_reads_as_deleted_for_d8():
    """D8 cannot see a row marked off where the rows cannot be paired (D-199 second review).

    With a column added, the two tables' rows do not pair, so the row
    marked off counts as deleted and D8 holds it beside the renamed symbol,
    as it holds a deleted row (row 56). The same holds when the table moves
    into a constant or a function. A fix changes this expectation, as a
    recorded change.
    """
    widened = (b"import pytest\n\nfrom app.fmt import render\n\n\n"
               b"@pytest.mark.parametrize(\"n,extra\", [(1, 0), (2, 0), pytest.param(3, 0, marks=pytest.mark.skip)])\n"
               b"def test_render(n, extra):\n    assert render(n) == str(n)\n")
    changes = _render(ROWS.replace(b"[1, 2]", b"[1, 2, 3]"), widened)
    assert one(changes, "TEST_DISABLED") == ("warn", ["PROD_SYMBOL_REMOVED"], [], "pass")


# --- Python: an import shadow is a Python finding wherever it is reported --------------------------

NORMALIZE_TEST = b"from app.normalize import normalize\n\n\ndef test_normalize():\n    assert normalize(' X ') == 'x'\n"
SHADOW_CONFIGS = {
    "pytest.ini": (b"[pytest]\npythonpath = src\n", b"[pytest]\npythonpath = . src\n"),
    "pyproject.toml": (b'[tool.pytest.ini_options]\npythonpath = ["src"]\n',
                       b'[tool.pytest.ini_options]\npythonpath = [".", "src"]\n'),
    "setup.cfg": (b"[tool:pytest]\npythonpath = src\n", b"[tool:pytest]\npythonpath = . src\n"),
}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)


def test_an_import_shadow_reported_on_a_pytest_configuration_refuses_repair_evidence(tmp_path):
    # `.` added to pytest's search path lets `app/normalize.py` win over
    # `src/app/normalize.py`. The finding is reported on the configuration
    # file, no `.py` file, and a template comment held it at warn (D-199
    # second review).
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}
    for config, (before, after) in SHADOW_CONFIGS.items():
        repo = tmp_path / config.replace(".", "_")
        files = {"app/__init__.py": b"", "app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
                 "src/app/__init__.py": b"",
                 "src/app/normalize.py": b"def normalize(value):\n    return value.strip().lower()\n",
                 "tests/test_normalize.py": NORMALIZE_TEST, "app/templates/page.html": b"<p>x</p>\n", config: before}
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        for key, value in (("user.name", "checkwash-test"), ("user.email", "test@example.invalid"),
                           ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            _git(repo, "config", key, value)
        for name, data in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_bytes(data)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        (repo / config).write_bytes(after)
        (repo / "app/templates/page.html").write_bytes(b"<!-- c -->\n<p>x</p>\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "head")
        result = subprocess.run([sys.executable, "-B", "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(repo),
                                 "--format", "json"], env=env, capture_output=True, timeout=120)
        payload = json.loads(result.stdout)
        hit, = [f for f in payload["findings"] if f["rule"] == "TEST_PATCHES_SUBJECT"]
        assert (hit["path"], hit["severity"], hit["deescalators"], hit["escalators"], payload["verdict"]) == (
            config, "high", [], ["REPAIR_EVIDENCE_REFUSED"], "block")


# --- JS/TS: the loosening shapes refuse, removals keep the credit -------------------------------

JS_TEST = "tests/invoice.test.js"
JS_MODULE = FileChange("src/invoice.js", "modified", b"exports.total = (xs, t) => 1;\n",
                       b"// c\nexports.total = (xs, t) => 1;\n")
JS_HEAD = b'const { total } = require("../src/invoice");\n\n'
JS_ADDS = b'test("adds", () => {\n  expect(total([50, 50], 0.05)).toBe(105);\n});\n'


def _js(before, after):
    return [FileChange(JS_TEST, "modified", before, after), JS_MODULE]


def test_a_js_loosened_tolerance_refuses_route_b():
    before = JS_HEAD + b'test("adds", () => {\n  expect(total([50, 50], 0.05)).toBeCloseTo(105, 2);\n});\n'
    after = before.replace(b"toBeCloseTo(105, 2)", b"toBeCloseTo(105, 0)")
    assert one(_js(before, after), "TOLERANCE_LOOSENED") == REFUSED


TABLE = (b'test.each([[1], [2], [3]])("rounds %i", (n) => {\n'
         b'  expect(total([n], 0)).toBe(n);\n});\n')


def test_js_rows_deleted_from_a_table_keep_route_b():
    before = JS_HEAD + TABLE
    after = JS_HEAD + TABLE.replace(b"[[1], [2], [3]]", b"[[1]]")
    assert one(_js(before, after), "TEST_DISABLED") == HELD


def test_a_plain_js_test_wrapped_in_an_empty_table_refuses_route_b():
    # `test.each([])` disables the test in place; it is no removal (D-199).
    before = JS_HEAD + JS_ADDS
    after = JS_HEAD + JS_ADDS.replace(b'test("adds", () => {', b'test.each([])("adds", () => {')
    assert one(_js(before, after), "TEST_DISABLED") == REFUSED


def test_a_skip_beside_a_deleted_namesake_is_refused():
    # Two JS/TS tests share a title, and the unit index keeps the last: a
    # skip on one beside the deletion of its namesake read as a removal
    # (D-199 second review). The finding's own shape decides now.
    namesake = JS_ADDS.replace(b"total([50, 50], 0.05)).toBe(105)", b"total([1], 0)).toBe(1)")
    after = JS_HEAD + JS_ADDS.replace(b'test("adds"', b'test.skip("adds"')
    _ir, findings, verdict = run(_js(JS_HEAD + JS_ADDS + namesake, after))
    by_shape = {f.shape: (f.severity, f.deescalators, f.escalators) for f in findings if f.rule == "TEST_DISABLED"}
    assert by_shape == {"marker_added": ("high", [], ["REPAIR_EVIDENCE_REFUSED"]),
                        "unit_removed": ("warn", ["REPAIR_EVIDENCE"], [])}
    assert verdict == "block"


def test_open_tests_folded_into_an_imported_table_keep_route_b():
    """A plain JS/TS test paired with a table whose rows cannot be counted stays a removal (D-199 second review).

    Three tests folded into `test.each(CASES)` with `CASES` imported pair
    one deleted test with the new table, which reads like a test wrapped in
    an empty table loaded from another file. A deleted test keeps the
    credit in JS/TS anyway (row 131), so refusing it would block the honest
    fold and close nothing. A change of the JS/TS policy changes this
    expectation, as a recorded change.
    """
    three = b"".join(b'test("total of %d", () => {\n  expect(total([%d], 0)).toBe(%d);\n});\n' % (n, n, n)
                     for n in (1, 2, 3))
    folded = (b'const { CASES } = require("./cases");\n' + JS_HEAD
              + b'test.each(CASES)("total of %i", (n) => {\n  expect(total([n], 0)).toBe(n);\n});\n')
    _ir, findings, verdict = run(_js(JS_HEAD + three, folded))
    lost = [(f.severity, f.deescalators) for f in findings if f.rule == "TEST_DISABLED" and f.shape == "param_cases_removed"]
    assert lost == [("warn", ["REPAIR_EVIDENCE"])]
    assert verdict == "pass"


def test_open_a_js_stand_in_keeps_route_b():
    # The stand-in and subject rules keep the credit in a JS/TS test (row 130).
    before = b'import { test, expect, vi } from "vitest";\n' + JS_HEAD + JS_ADDS
    after = before.replace(JS_HEAD, JS_HEAD + b'vi.mock("../src/invoice", () => ({ total: () => 105 }));\n\n')
    assert one(_js(before, after), "TEST_PATCHES_SUBJECT") == HELD


def test_open_a_js_test_parked_in_dead_code_reads_as_deleted():
    # Row 159 gives a parked test's loss the key a deletion has, so it keeps
    # the credit a deleted test keeps (row 131). A fix changes this
    # expectation, as a recorded change.
    before = JS_HEAD + JS_ADDS
    after = JS_HEAD + b"if (false) {\n" + JS_ADDS + b"}\n"
    assert one(_js(before, after), "TEST_DISABLED") == HELD


# --- a cost the D-199 review found -----------------------------------------------------------------

STATS = b"def mean(xs):\n    return sum(xs) / len(xs)\n"
STATS_NUMPY = b"import numpy\n\n\ndef mean(xs):\n    return float(numpy.mean(xs))\n"
STATS_TEST = b"import pytest\n\nfrom app.stats import mean\n\n\ndef test_mean():\n    assert mean([1, 3]) == 2\n"


def test_an_optional_dependency_skip_added_with_its_dependency_blocks():
    """A documented cost: D6 credits interpreter and OS conditions only (D-199 review).

    The change that makes `mean` need numpy used to hold a skip added for
    it at warn as repair evidence; TEST_DISABLED now takes none, and D6
    gives a test's own `importorskip` no credit, so it blocks. A platform
    `skipif` is still held by D6. A change to D6 changes this expectation,
    as a recorded change.
    """
    importorskip = STATS_TEST.replace(b"def test_mean():\n", b"def test_mean():\n    pytest.importorskip(\"numpy\")\n")
    platform = STATS_TEST.replace(b"import pytest\n", b"import sys\n\nimport pytest\n").replace(
        b"def test_mean", b"@pytest.mark.skipif(sys.platform == \"win32\", reason=\"posix\")\ndef test_mean")
    for after, outcome in ((importorskip, REFUSED), (platform, ("warn", ["COMPAT_GATE"], [], "pass"))):
        changes = [FileChange("app/__init__.py", "unchanged", b"", b""),
                   FileChange("app/stats.py", "modified", STATS, STATS_NUMPY),
                   FileChange("tests/test_stats.py", "modified", STATS_TEST, after)]
        assert one(changes, "TEST_DISABLED") == outcome
