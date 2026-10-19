"""A production file the diff adds does not explain a rewritten stored expectation (#463).

The file-scoped EXPECTED_VALUE_CHANGED (#129) is not raised when a Python
production symbol changed, or an opaque production change exists, anywhere
in the diff. An added Python production file put every symbol it defines
into `prod_symbols_changed`, so one new module holding `X = 1` silenced a
rewritten golden file: SNAPSHOT_CODE_COCHANGE stayed at warn, and nothing
at all was left once any test logic changed.

Ruling 463 (owner, 2026-10-18, issuecomment-6248011246, 「照建議」): Q1 (a),
a Python production file the diff adds no longer counts as an
implementation change for the snapshot form, and a deleted one still does;
Q2 (a), the check stays diff-global; Q3 (a), an opaque production change
still counts; Q4 (a), SNAPSHOT_CODE_COCHANGE keeps its test-logic condition,
and the escape through a test unit added in an unrelated file is a named
residual (THREATMODEL row 132). The `.gwcase` fixtures `snapshot_new_prod_*`,
`snapshot_unrelated_symbol_edit_*`, `snapshot_template_comment_edit_neg` and
`snapshot_deleted_prod_module_neg` carry the reproductions end to end.
"""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.snapshot_expectation import detect
from checkwash.engine import analyze
from checkwash.ir.model import DiffGlobals, to_jsonable

TODAY = datetime.date(2026, 10, 19)
GOLDEN = FileChange("tests/golden/invoice.txt", "modified", b"105.3\n", b"104.0\n")
NEW_TEST = FileChange("tests/test_smoke.py", "added", None, b"def test_smoke():\n    assert 1 + 1 == 2\n")
NO_OP_EDIT = FileChange(
    "app/rounding.py", "modified",
    b"def round_total(x):\n    return x\n", b"def round_total(x):\n    return x + 0\n",
)
REWRITE = ("EXPECTED_VALUE_CHANGED", "high", GOLDEN.path)
COCHANGE = ("SNAPSHOT_CODE_COCHANGE", "warn", GOLDEN.path)


def check(*changes):
    ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY)
    return ir, sorted((f.rule, f.severity, f.path) for f in findings), verdict


def added(path, source):
    return FileChange(path, "added", None, source)


# --- Q1 (a): an added Python production file is no implementation change ------------------


@pytest.mark.parametrize("source", [
    pytest.param(b"X = 1\n", id="binding"),
    pytest.param(b"X: int = 1\n", id="annotated-binding"),
    pytest.param(b"def unrelated():\n    return 3\n", id="function"),
    pytest.param(b"class Unused:\n    pass\n", id="class"),
])
def test_an_added_production_module_does_not_explain_a_rewritten_golden_file(source):
    _ir, findings, verdict = check(GOLDEN, added("app/_unused.py", source))
    assert verdict == "block"
    assert findings == [REWRITE, COCHANGE]


@pytest.mark.parametrize("path,module", [
    ("unused.py", "unused"),
    ("src/app/unused.py", "app.unused"),
    ("app/extra/__init__.py", "app.extra"),
])
def test_wherever_the_added_module_lives(path, module):
    ir, findings, verdict = check(GOLDEN, added(path, b"X = 1\n"))
    assert ir.globals.prod_symbols_in_added_files == [f"{module}::X"]
    assert verdict == "block"
    assert findings == [REWRITE, COCHANGE]


def test_the_ir_names_what_an_added_file_contributed_and_keeps_it_a_changed_symbol():
    # A comment-only edit to an existing module changes no symbol, as before.
    ir, findings, verdict = check(
        GOLDEN,
        added("app/_unused.py", b"X = 1\n\n\ndef helper():\n    return X\n"),
        FileChange("app/billing.py", "modified", b"def total():\n    return 1\n",
                   b"def total():\n    return 1  # unchanged\n"),
    )
    assert ir.globals.prod_symbols_in_added_files == ["app._unused::X", "app._unused::helper"]
    assert ir.globals.prod_symbols_changed == ["app._unused::X", "app._unused::helper"]
    assert verdict == "block"
    assert findings == [REWRITE, COCHANGE]


def test_a_deleted_production_module_still_counts():
    # Q1 (a), not (b): a deleted module can honestly retire its golden file.
    ir, findings, verdict = check(
        GOLDEN, FileChange("app/legacy.py", "deleted", b"def old():\n    return 1\n", None),
    )
    assert ir.globals.prod_symbols_changed == ["app.legacy::old"]
    assert ir.globals.prod_symbols_in_added_files == []
    assert verdict == "pass"
    assert findings == [COCHANGE]


@pytest.mark.parametrize("path,source", [
    pytest.param("app/rates.json", b'{"rate": 1}\n', id="data-file"),
    pytest.param("app/broken.py", b"def broken(:\n", id="unparseable-python"),
])
def test_an_added_file_checkwash_cannot_read_never_counted(path, source):
    # Not opaque either: opacity needs a change to something that was
    # already production (THREATMODEL row 73).
    ir, findings, verdict = check(GOLDEN, added(path, source))
    assert not ir.globals.prod_opaque_change
    assert ir.globals.prod_symbols_in_added_files == []
    assert verdict == "block"
    assert findings == [REWRITE, COCHANGE]


def test_a_modified_module_that_shares_an_added_modules_name_still_counts():
    # `pkg.py` and `pkg/__init__.py` are both module `pkg`, so each gives
    # `pkg::X`; the multiset difference keeps the modified one.
    ir, findings, verdict = check(
        GOLDEN, added("pkg.py", b"X = 1\n"),
        FileChange("pkg/__init__.py", "modified", b"X = 0\n", b"X = 1\n"),
    )
    assert sorted(ir.globals.prod_symbols_changed) == ["pkg::X", "pkg::X"]
    assert ir.globals.prod_symbols_in_added_files == ["pkg::X"]
    assert verdict == "pass"
    assert findings == [COCHANGE]


# --- Q2 (a), Q3 (a), Q4 (a): what still counts and what stays as it was -------------------


def test_a_changed_symbol_in_an_existing_module_still_counts_beside_an_added_one():
    _ir, findings, verdict = check(GOLDEN, added("app/_unused.py", b"X = 1\n"), NO_OP_EDIT)
    assert verdict == "pass"
    assert findings == [COCHANGE]


def test_an_opaque_production_change_still_counts_beside_an_added_module():
    template = FileChange(
        "app/templates/invoice.html", "modified",
        b"<!-- invoice -->\n<p>{{ total }}</p>\n", b"<!-- invoice, rounded -->\n<p>{{ total }}</p>\n",
    )
    ir, findings, verdict = check(GOLDEN, added("app/_unused.py", b"X = 1\n"), template)
    assert ir.globals.prod_opaque_change
    assert verdict == "pass"
    assert findings == [COCHANGE]


def test_a_new_unrelated_test_silences_only_the_cochange_warning():
    ir, findings, verdict = check(GOLDEN, added("app/_unused.py", b"X = 1\n"), NEW_TEST)
    assert ir.globals.test_logic_changed
    assert verdict == "block"
    assert findings == [REWRITE]


# --- the cost, open for the owner's decision (D-157): a pytest file under golden/ --------


GOLDEN_TEST = "tests/golden/test_x.py"
GOLDEN_TEST_EDIT = FileChange(
    GOLDEN_TEST, "modified",
    b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n",
    b"from app.billing import total\nfrom app.feature import double\n\n\n"
    b"def test_total():\n    assert total() == 78.75\n\n\n"
    b"def test_double():\n    assert double(21) == 42\n",
)
FEATURE = FileChange("app/feature.py", "added", None, b"def double(x):\n    return x * 2\n")


@pytest.mark.parametrize("extra,expected,expected_verdict", [
    pytest.param((), [("EXPECTED_VALUE_CHANGED", "high", GOLDEN_TEST)], "block",
                 id="beside-the-new-module-only"),
    pytest.param((NO_OP_EDIT,), [], "pass", id="beside-a-changed-existing-symbol"),
])
def test_a_test_added_for_a_new_module_to_a_pytest_file_under_golden(extra, expected, expected_verdict):
    # A pytest file kept under golden/ is a stored expectation as well as a
    # test (#219), so adding a test to it rewrites it. Before #463 the new
    # module's symbols silenced the file-scoped form and the new test
    # silenced SNAPSHOT_CODE_COCHANGE, so the first case passed. Pinned as
    # current behaviour, not as a judgement that the edit is dishonest:
    # whether Q1 (a) accepts this cost is open (D-157, THREATMODEL row 132).
    ir, findings, verdict = check(GOLDEN_TEST_EDIT, FEATURE, *extra)
    assert [(file.role, file.test_obligations) for file in ir.files if file.path == GOLDEN_TEST] == [
        ("snapshot", True)]
    assert ir.globals.test_logic_changed
    assert ir.globals.prod_symbols_in_added_files == ["app.feature::double"]
    assert verdict == expected_verdict
    assert findings == expected


# --- the detector reads the new field and nothing else new -------------------------------


@pytest.mark.parametrize("changed,in_added,opaque,fires", [
    pytest.param([], [], False, True, id="no-symbol"),
    pytest.param(["app._unused::X"], ["app._unused::X"], False, True, id="added-only"),
    pytest.param(["app._unused::X", "app.rounding::round_total"], ["app._unused::X"], False, False,
                 id="added-and-existing"),
    pytest.param(["pkg::X", "pkg::X"], ["pkg::X"], False, False, id="same-name-twice"),
    pytest.param(["app.rounding::round_total"], [], False, False, id="existing-only"),
    pytest.param(["app._unused::X"], ["app._unused::X"], True, False, id="added-and-opaque"),
])
def test_only_a_symbol_no_added_file_contributed_counts(changed, in_added, opaque, fires):
    ir, _findings, _verdict = check(GOLDEN)
    ir.globals.prod_symbols_changed = list(changed)
    ir.globals.prod_symbols_in_added_files = list(in_added)
    ir.globals.prod_opaque_change = opaque
    assert [f.rule for f in detect(ir)] == (["EXPECTED_VALUE_CHANGED"] if fires else [])


def test_the_field_round_trips_and_an_ir_without_it_counts_every_symbol():
    # A new optional field, so IR_VERSION stays 2 (docs/stability.md).
    ir, _findings, _verdict = check(GOLDEN, added("app/_unused.py", b"X = 1\n"))
    payload = json.loads(json.dumps(to_jsonable(ir.globals)))
    assert payload["prod_symbols_in_added_files"] == ["app._unused::X"]
    ir.globals = DiffGlobals(**payload)
    assert [f.rule for f in detect(ir)] == ["EXPECTED_VALUE_CHANGED"]
    del payload["prod_symbols_in_added_files"]
    ir.globals = DiffGlobals(**payload)
    assert detect(ir) == []
