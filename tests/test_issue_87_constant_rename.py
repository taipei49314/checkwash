"""Issue #87's complete ten-occurrence rename retains all seven test oracles."""
import datetime

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


BEFORE = "from billing import invoice_total\nfrom reference import reference_total\nITEMS = [20, 50]\n"
BEFORE += "\n".join(
    f"def test_total_{number}():\n    assert invoice_total(ITEMS) == "
    + ("reference_total(ITEMS)" if number < 2 else "73.5") + "\n"
    for number in range(7)
)
AFTER = BEFORE.replace("ITEMS", "INVOICE_ITEMS")


def test_all_ten_occurrences_are_one_consistent_literal_rename():
    assert BEFORE.count("ITEMS") == AFTER.count("INVOICE_ITEMS") == 10
    ir, findings, verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", BEFORE.encode(), AFTER.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
    )
    assert verdict == "pass"
    assert not findings
    assert len(ir.files[0].units) == 7
    assert ir.files[0].module_constant_renames == {"ITEMS": "INVOICE_ITEMS"}


def test_renamed_suite_still_distinguishes_correct_and_buggy_tax(tmp_path):
    import os
    import subprocess
    import sys

    statuses = []
    for correct in (True, False):
        for name, source in (("before", BEFORE), ("after", AFTER)):
            checkout = tmp_path / f"{correct}-{name}"
            checkout.mkdir()
            (checkout / "billing.py").write_text(
                "def invoice_total(items):\n    return sum(items)" + (" * 1.05" if correct else "") + "\n",
                encoding="utf-8",
            )
            (checkout / "reference.py").write_text(
                "def reference_total(items):\n    return sum(items) * 1.05\n", encoding="utf-8",
            )
            (checkout / "test_billing.py").write_text(source, encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_billing.py"],
                                    cwd=checkout, capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"))
            statuses.append(result.returncode)
    assert statuses == [0, 0, 1, 1]
