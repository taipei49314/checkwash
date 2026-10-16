"""Issue #419: a weakening-class finding in a Python test or conftest refuses
the opaque-change credit (ruling Q1 (b) and Q5 (b), 2026-10-14).

A byte edit to a production file checkwash does not parse (a template, C or
Rust, a data file, a shell script that runs no tests, a JS module) sets
`prod_opaque_change`, and that credit held every oracle finding in the diff
at warn. ASSERT_WEAKENED, ASSERT_REMOVED, TEST_DISABLED, TOLERANCE_LOOSENED
and BROAD_EXCEPT_ADDED in a Python test or conftest refuse it now. Symbol
evidence still holds them. A refused finding that reaches high says why, with
OPAQUE_PROD_CHANGE_NOT_EVIDENCE: still E1, only the sentence differs.

The .gwcase fixtures carry the end-to-end shapes: the opaque_refused_* and
*_still_opaque_pos cases block, a JS/TS test keeps the credit
(opaque_residual_js_assert_weakened_template_neg), and a guarded conftest
control is held by COMPAT_GATE instead (conftest_hook_guard_opaque_prod_neg).
"""
import datetime

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gating import OPAQUE_REFUSED_RULES, ORACLE_RULES

TODAY = datetime.date(2026, 10, 16)
TEST_PATH = "tests/test_billing.py"
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
FIXED = b"def compute_invoice_total(items):\n    return round(sum(items), 2)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")
# A data file nothing parses: the same opaque change #415's `data_read` uses.
DATA = FileChange("data/rates.csv", "modified", b"rate,1\n", b"rate,2\n")
# broad_except_in_test_pos, verbatim.
CACHE = (b"from cache import Cache\n\n\n"
         b"def test_miss_on_newer_version():\n"
         b"    c = Cache()\n"
         b'    c.put("k", "v1", version=1)\n'
         b'    assert c.get("k", version=2) is None\n')
SWALLOWED = CACHE.replace(
    b'    assert c.get("k", version=2) is None\n',
    b"    try:\n"
    b'        assert c.get("k", version=2) is None\n'
    b"    except Exception:\n"
    b"        pass  # cache invalidation behaviour is environment dependent\n",
)

FROZEN = {
    "ASSERT_REMOVED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "BROAD_EXCEPT_ADDED",
}


def _run(*changes):
    ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY)
    return ir, [(f.rule, f.severity, f.escalators, f.deescalators) for f in findings], verdict


def test_membership_is_frozen_here():
    # Which findings refuse the credit is a ruling (#419 Q1 and Q8). Moving
    # a rule in or out is a visible edit to this file, not a quiet one there.
    assert OPAQUE_REFUSED_RULES == FROZEN


def test_broad_except_is_the_one_member_outside_oracle_rules():
    assert OPAQUE_REFUSED_RULES - ORACLE_RULES == {"BROAD_EXCEPT_ADDED"}


def test_a_python_weakening_beside_an_opaque_change_blocks_and_says_why():
    ir, findings, verdict = _run(FileChange(TEST_PATH, "modified", TEST, WEAKENED), DATA)
    assert ir.globals.prod_opaque_change is True
    assert findings == [("ASSERT_WEAKENED", "high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])]
    assert verdict == "block"


def test_symbol_evidence_still_holds_it_beside_the_same_opaque_change():
    _ir, findings, verdict = _run(
        FileChange(TEST_PATH, "modified", TEST, WEAKENED),
        FileChange("billing.py", "modified", BILLING, FIXED),
        DATA,
    )
    assert findings == [("ASSERT_WEAKENED", "warn", [], ["REPAIR_EVIDENCE"])]
    assert verdict == "pass"


def test_with_no_production_change_the_old_wording_stays():
    _ir, findings, verdict = _run(FileChange(TEST_PATH, "modified", TEST, WEAKENED))
    assert findings == [("ASSERT_WEAKENED", "high", ["NO_PROD_CHANGE_IN_DIFF"], [])]
    assert verdict == "block"


def test_a_broad_except_in_a_python_test_had_no_other_route():
    _ir, findings, verdict = _run(FileChange("tests/test_cache.py", "modified", CACHE, SWALLOWED), DATA)
    broad = [(severity, up, down) for rule, severity, up, down in findings if rule == "BROAD_EXCEPT_ADDED"]
    assert broad == [("high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])]
    assert verdict == "block"
