"""The demo in examples/invoice must stay reproducible, forever.

The launch pitch rests on "clone it and see for yourself". A demo that has
silently rotted is worse than none, so it is a test: the weakening blocks,
the honest fix stays silent.
"""

import datetime
import pathlib

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze

ROOT = pathlib.Path(__file__).resolve().parent.parent / "examples" / "invoice"
TODAY = datetime.date(2026, 1, 1)


def _bytes(rel: str) -> bytes:
    return (ROOT / rel).read_bytes()


def test_weakening_the_oracle_blocks():
    before = _bytes("tests/test_billing.py")
    after = before.replace(b"== 35.37", b"> 0")
    assert after != before, "demo test file no longer contains the '== 35.37' assertion"
    changes = [FileChange("tests/test_billing.py", "modified", before, after)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_WEAKENED" and f.severity == "high" for f in findings)


def test_honest_fix_stays_silent():
    prod_before = _bytes("billing.py")
    prod_after = prod_before.replace(
        b"return sum(price * qty for price, qty in items)",
        b"return round(sum(price * qty for price, qty in items), 2)",
    )
    assert prod_after != prod_before, "demo billing.py no longer matches the documented fix"
    changes = [FileChange("billing.py", "modified", prod_before, prod_after)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY)
    assert verdict == "pass"
    assert not findings
