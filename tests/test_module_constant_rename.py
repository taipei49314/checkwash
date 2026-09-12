"""A whole-file literal constant rename preserves reference-side oracles."""
import datetime
import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from billing import invoice_total
from reference import reference_total
ITEMS = [20, 50]
def test_total():
    assert invoice_total(ITEMS) == reference_total(ITEMS)
'''


def run(after):
    return analyze([FileChange("tests/test_billing.py", "modified", BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 12))


def test_constant_renamed_on_both_sides_preserves_oracle():
    ir, findings, verdict = run(BEFORE.replace("ITEMS", "INVOICE_ITEMS"))
    assert ir.files[0].module_constant_renames == {"ITEMS": "INVOICE_ITEMS"}
    assert not findings and verdict == "pass"


@pytest.mark.parametrize("after", [
    BEFORE.replace("ITEMS", "INVOICE_ITEMS").replace("[20, 50]", "[1]"),
    BEFORE.replace("ITEMS", "INVOICE_ITEMS").replace("reference_total(INVOICE_ITEMS)", "0"),
    BEFORE.replace("ITEMS", "INVOICE_ITEMS").replace("def test_total():", "def test_total(INVOICE_ITEMS):"),
])
def test_rename_proof_does_not_cover_behavior_change_or_shadow(after):
    ir, _, _ = run(after)
    assert not ir.files[0].module_constant_renames


def test_rename_with_expected_literal_change_still_blocks():
    _, findings, verdict = run(BEFORE.replace("ITEMS", "INVOICE_ITEMS").replace("reference_total(INVOICE_ITEMS)", "0"))
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("extra", [
    '\nfrom other import INVOICE_ITEMS\n',
    '\ndef helper():\n    try:\n        pass\n    except ValueError as INVOICE_ITEMS:\n        print(ITEMS)\n',
    '\ndef helper(value):\n    match value:\n        case {"value": INVOICE_ITEMS}:\n            print(ITEMS)\n',
    '\ndef helper(value):\n    match value:\n        case {"value": captured, **INVOICE_ITEMS}:\n            print(ITEMS)\n',
    '\ndef helper():\n    return sys.modules[__name__].__dict__["ITEMS"]\n',
])
def test_capture_and_reflective_lookup_withhold_rename_proof(extra):
    from checkwash.frontends.python.constant_renames import literal_constant_renames
    before = BEFORE + extra
    # Rename only Name-like use sites; leave existing captures/string keys
    # intact, because they are precisely the collision the proof must reject.
    after = BEFORE.replace("ITEMS", "INVOICE_ITEMS") + extra.replace("print(ITEMS)", "print(INVOICE_ITEMS)")
    assert literal_constant_renames(before.encode(), after.encode()) == {}
