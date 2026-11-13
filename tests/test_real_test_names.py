"""Real Python test names on findings emitted from projected concrete IR units (D-210)."""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from checkwash import cli
from checkwash.allowlist import AllowEntry
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors import REGISTRY
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import ParsedFile, ParsedUnit, parse_python
from checkwash.gating import apply_gates
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import (
    Assertion,
    DiffGlobals,
    IR,
    Unit,
    UnitSide,
    to_jsonable,
)

TODAY = datetime.date(2026, 11, 14)

BILLING_PY = (
    "def invoice_total(lines, tax_rate=0.053):\n"
    "    subtotal = sum(qty * price for qty, price in lines)\n"
    "    return round(subtotal * (1 + tax_rate), 2)\n\n\n"
    "def apply_discount(total, percent):\n"
    "    return round(total * (1 - percent / 100), 2)\n"
)


def _run_mem(
    before_files: dict[str, str],
    after_files: dict[str, str],
    *,
    base_repo: dict[str, str] | None = None,
    allow_entries: list[AllowEntry] | None = None,
):
    repo_before = {**(base_repo or {}), **before_files}
    repo_after = {**(base_repo or {}), **after_files}
    old_bytes = {p: s.encode("utf-8") for p, s in repo_before.items()}
    new_bytes = {p: s.encode("utf-8") for p, s in repo_after.items()}
    changes = [
        FileChange(
            path=p,
            before=old_bytes.get(p),
            after=new_bytes.get(p),
            status="modified" if p in old_bytes and p in new_bytes else "added" if p in new_bytes else "deleted",
        )
        for p in sorted(set(before_files) | set(after_files))
        if old_bytes.get(p) != new_bytes.get(p)
    ]
    roots = {
        p.split("/", 1)[0].removesuffix(".py")
        for p in repo_after
        if p.endswith(".py") and not p.startswith("tests/")
    }
    return analyze(
        changes,
        Config(),
        Contract(),
        allow_entries or [],
        TODAY,
        known_modules=roots or {"billing"},
        self_modules=roots or {"billing"},
        head_reader=new_bytes.get,
        head_searcher=lambda needles: search_source_mapping(new_bytes, needles),
        root_reader=new_bytes.get,
        root_searcher=lambda needles: search_source_mapping(new_bytes, needles),
    )


@pytest.mark.parametrize(
    "case_id,before_test,after_test,expected_unit,expected_before,expected_after",
    [
        (
            "v0_readme_local_capture",
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.3\n"
            ),
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.0\n"
            ),
            "test_invoice_total",
            "assert total == 105.3",
            "assert total == 105.0",
        ),
        (
            "v1_two_single_assert_tests_with_local",
            (
                "from billing import apply_discount, invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.3\n\n\n"
                "def test_apply_discount():\n"
                "    assert apply_discount(200.0, 25) == 150.0\n"
            ),
            (
                "from billing import apply_discount, invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.3\n\n\n"
                "def test_apply_discount():\n"
                "    assert apply_discount(200.0, 25) == 160.0\n"
            ),
            "test_apply_discount",
            "assert apply_discount(200.0, 25) == 150.0",
            "assert apply_discount(200.0, 25) == 160.0",
        ),
        (
            "v2_two_asserts_in_one_test",
            (
                "from billing import apply_discount, invoice_total\n\n\n"
                "def test_billing():\n"
                "    assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.3\n"
                "    assert apply_discount(200.0, 25) == 150.0\n"
            ),
            (
                "from billing import apply_discount, invoice_total\n\n\n"
                "def test_billing():\n"
                "    assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.3\n"
                "    assert apply_discount(200.0, 25) == 160.0\n"
            ),
            "test_billing",
            "assert apply_discount(200.0, 25) == 150.0",
            "assert apply_discount(200.0, 25) == 160.0",
        ),
        (
            "v3_direct_single_assert",
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.3\n"
            ),
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.0\n"
            ),
            "test_invoice_total",
            "assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.3",
            "assert invoice_total([(2, 25.0), (1, 50.0)]) == 105.0",
        ),
        (
            "v4_unittest_testcase",
            (
                "import unittest\n\nfrom billing import invoice_total\n\n\n"
                "class BillingTest(unittest.TestCase):\n"
                "    def test_invoice_total(self):\n"
                "        self.assertEqual(invoice_total([(2, 25.0), (1, 50.0)]), 105.3)\n"
            ),
            (
                "import unittest\n\nfrom billing import invoice_total\n\n\n"
                "class BillingTest(unittest.TestCase):\n"
                "    def test_invoice_total(self):\n"
                "        self.assertEqual(invoice_total([(2, 25.0), (1, 50.0)]), 105.0)\n"
            ),
            "BillingTest.test_invoice_total",
            "self.assertEqual(invoice_total([(2, 25.0), (1, 50.0)]), 105.3)",
            "self.assertEqual(invoice_total([(2, 25.0), (1, 50.0)]), 105.0)",
        ),
        (
            "v5_parametrize_cell_rewrite",
            (
                "import pytest\n\nfrom billing import apply_discount\n\n\n"
                '@pytest.mark.parametrize("total, percent, expected", [(200.0, 25, 150.0), (100.0, 10, 90.0)])\n'
                "def test_apply_discount(total, percent, expected):\n"
                "    assert apply_discount(total, percent) == expected\n"
            ),
            (
                "import pytest\n\nfrom billing import apply_discount\n\n\n"
                '@pytest.mark.parametrize("total, percent, expected", [(200.0, 25, 150.0), (100.0, 10, 95.0)])\n'
                "def test_apply_discount(total, percent, expected):\n"
                "    assert apply_discount(total, percent) == expected\n"
            ),
            "test_apply_discount",
            "assert apply_discount(total, percent) == expected",
            "assert apply_discount(total, percent) == expected",
        ),
        (
            "v6_renamed_test_with_local_capture",
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.3\n"
            ),
            (
                "from billing import invoice_total\n\n\n"
                "def test_invoice_total_with_tax():\n"
                "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
                "    assert total == 105.0\n"
            ),
            "test_invoice_total_with_tax",
            None,
            None,
        ),
    ],
)
def test_repro07_all_seven_module_shapes_report_real_python_test_names(
    case_id,
    before_test,
    after_test,
    expected_unit,
    expected_before,
    expected_after,
):
    _ir, findings, verdict = _run_mem(
        {"tests/test_billing.py": before_test},
        {"tests/test_billing.py": after_test},
        base_repo={"billing.py": BILLING_PY},
    )
    assert verdict == "block", case_id
    assert len(findings) == 1, (case_id, findings)
    f = findings[0]
    assert f.severity == "high"
    assert f.unit == expected_unit
    assert "test_concrete_" not in f.unit
    assert "test_concrete_" not in f.message
    assert "test_concrete_" not in f.fingerprint
    if expected_before is not None:
        assert f.before is not None and f.before.text == expected_before
    if expected_after is not None:
        assert f.after is not None and f.after.text == expected_after


def test_repro06_cochanged_prod_and_test_only_share_unit_evidence_and_fingerprint():
    before_test = (
        "from billing import invoice_total\n\n\n"
        "def test_invoice_total():\n"
        "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
        "    assert total == 105.3\n"
    )
    after_test = before_test.replace("== 105.3", "== 105.0")
    noop_billing = BILLING_PY.replace(
        "subtotal = sum(qty * price for qty, price in lines)",
        "subtotal = sum(qty * price for qty, price in lines) + 0",
    )

    _ir_a2, findings_a2, verdict_a2 = _run_mem(
        {"billing.py": BILLING_PY, "tests/test_billing.py": before_test},
        {"billing.py": noop_billing, "tests/test_billing.py": after_test},
    )
    _ir_a2b, findings_a2b, verdict_a2b = _run_mem(
        {"tests/test_billing.py": before_test},
        {"tests/test_billing.py": after_test},
        base_repo={"billing.py": BILLING_PY},
    )

    assert verdict_a2 == "pass"
    assert verdict_a2b == "block"
    assert len(findings_a2) == len(findings_a2b) == 1
    fa2, fa2b = findings_a2[0], findings_a2b[0]
    assert fa2.unit == fa2b.unit == "test_invoice_total"
    assert fa2.before == fa2b.before
    assert fa2.after == fa2b.after
    assert fa2.before is not None and fa2.before.text == "assert total == 105.3"
    assert fa2.after is not None and fa2.after.text == "assert total == 105.0"
    assert fa2.fingerprint == fa2b.fingerprint


def test_captured_result_special_authorities_and_local_rename_guards():
    # 1. `is None` -> `== pytest.approx(...)` on a captured variable MUST keep
    #    the projected None-literal proof (blocking as EXPECTED_VALUE_CHANGED
    #    rather than looking like a 30 -> 80 strength increase) while reporting
    #    the real test name.
    flags_py = "def check_flag(x):\n    return None\n"
    before_flag = (
        "import pytest\nfrom flags import check_flag\n\n\n"
        "def test_flag():\n"
        "    got = check_flag(1)\n"
        "    assert got is None\n"
    )
    after_flag = (
        "import pytest\nfrom flags import check_flag\n\n\n"
        "def test_flag():\n"
        "    got = check_flag(1)\n"
        "    assert got == pytest.approx(0.0, abs=1e-3)\n"
    )
    ir_flag, findings_flag, verdict_flag = _run_mem(
        {"tests/test_flags.py": before_flag},
        {"tests/test_flags.py": after_flag},
        base_repo={"flags.py": flags_py},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_flag.files[0].units)
    assert verdict_flag == "block"
    assert [f.rule for f in findings_flag] == ["EXPECTED_VALUE_CHANGED"]
    assert findings_flag[0].unit == "test_flag"
    assert "test_concrete_" not in findings_flag[0].fingerprint

    # 2. Local variable rename + expectation rewrite projects cleanly without
    #    spurious ASSERT_SUBSTITUTED and reports the real function name.
    before_local = (
        "from billing import invoice_total\n\n\n"
        "def test_invoice_total():\n"
        "    total = invoice_total([(2, 25.0), (1, 50.0)])\n"
        "    assert total == 105.3\n"
    )
    after_local_changed = (
        "from billing import invoice_total\n\n\n"
        "def test_invoice_total():\n"
        "    result = invoice_total([(2, 25.0), (1, 50.0)])\n"
        "    assert result == 105.0\n"
    )
    _ir_chg, findings_chg, verdict_chg = _run_mem(
        {"tests/test_billing.py": before_local},
        {"tests/test_billing.py": after_local_changed},
        base_repo={"billing.py": BILLING_PY},
    )
    assert verdict_chg == "block"
    assert [f.rule for f in findings_chg] == ["EXPECTED_VALUE_CHANGED"]
    assert findings_chg[0].unit == "test_invoice_total"

    # 3. Pure local variable rename with unchanged expectation passes cleanly.
    after_local_same = after_local_changed.replace("== 105.0", "== 105.3")
    _ir_same, findings_same, verdict_same = _run_mem(
        {"tests/test_billing.py": before_local},
        {"tests/test_billing.py": after_local_same},
        base_repo={"billing.py": BILLING_PY},
    )
    assert verdict_same == "pass"
    assert findings_same == []

    # 4. Literal-left operand flip (`assert total == 105.3` -> `assert 105.3 == total`)
    #    retains projection under `primitive_string_result` rather than skipping.
    num_py = "def label_code(x):\n    return '105'\n"
    before_flip = (
        "from num import label_code\n\n\n"
        "def test_code():\n"
        "    got = label_code(1)\n"
        "    assert got == '105'\n"
    )
    after_flip = (
        "from num import label_code\n\n\n"
        "def test_code():\n"
        "    got = label_code(1)\n"
        "    assert '105' == got\n"
    )
    ir_flip, findings_flip, verdict_flip = _run_mem(
        {"tests/test_num.py": before_flip},
        {"tests/test_num.py": after_flip},
        base_repo={"num.py": num_py},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_flip.files[0].units)
    assert verdict_flip == "pass"
    assert findings_flip == []

    # 5. `_requires_derived_authority = frozenset()` (falsy set!) still triggers
    #    projection so proved derived-string equivalence passes cleanly.
    digits_py = "def digits_only(s):\n    return ''.join(c for c in s if c.isdigit())\n"
    before_deriv = (
        "from digits import digits_only\n\n\n"
        "def test_digits():\n"
        '    got = digits_only("a1b2")\n'
        '    assert got == "12"\n'
    )
    after_deriv = (
        "from digits import digits_only\n\n\n"
        "def test_digits():\n"
        '    got = digits_only("a1b2")\n'
        '    assert got == "".join(ch for ch in "a1b2" if ch.isdigit())\n'
    )
    ir_deriv, findings_deriv, verdict_deriv = _run_mem(
        {"tests/test_digits.py": before_deriv},
        {"tests/test_digits.py": after_deriv},
        base_repo={"digits.py": digits_py},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_deriv.files[0].units)
    assert verdict_deriv == "pass"
    assert findings_deriv == []


def test_projected_consolidation_sites_report_real_qualified_and_numbered_names():
    # 1. Top-level loop consolidation with one rewritten expected value.
    before_loop = (
        "from billing import apply_discount\n\n\n"
        "def test_first():\n"
        "    assert apply_discount(200.0, 25) == 150.0\n\n\n"
        "def test_second():\n"
        "    assert apply_discount(100.0, 10) == 90.0\n"
    )
    after_loop = (
        "from billing import apply_discount\n\n\n"
        "def test_discounts():\n"
        "    for total, pct, want in [(200.0, 25, 150.0), (100.0, 10, 95.0)]:\n"
        "        assert apply_discount(total, pct) == want\n"
    )
    ir_loop, findings_loop, verdict_loop = _run_mem(
        {"tests/test_billing.py": before_loop},
        {"tests/test_billing.py": after_loop},
        base_repo={"billing.py": BILLING_PY},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_loop.files[0].units)
    assert verdict_loop == "block"
    assert [f.unit for f in findings_loop] == ["test_discounts"]

    # 2. Plain class method consolidation preserves `Class.test_method`.
    before_cls = (
        "from billing import apply_discount\n\n\n"
        "class TestDiscounts:\n"
        "    def test_first(self):\n"
        "        assert apply_discount(200.0, 25) == 150.0\n\n"
        "    def test_second(self):\n"
        "        assert apply_discount(100.0, 10) == 90.0\n"
    )
    after_cls = (
        "from billing import apply_discount\n\n\n"
        "class TestDiscounts:\n"
        "    def test_rates(self):\n"
        "        for total, pct, want in [(200.0, 25, 150.0), (100.0, 10, 95.0)]:\n"
        "            assert apply_discount(total, pct) == want\n"
    )
    ir_cls, findings_cls, verdict_cls = _run_mem(
        {"tests/test_billing.py": before_cls},
        {"tests/test_billing.py": after_cls},
        base_repo={"billing.py": BILLING_PY},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_cls.files[0].units)
    assert verdict_cls == "block"
    assert [f.unit for f in findings_cls] == ["TestDiscounts.test_rates"]

    # 3. Duplicate-named live functions (`if/else`) in `parse_python` preserve `#2` in `source_unit_map`.
    from checkwash.frontends.python.table_oracles import resolve_source_unit, source_unit_map

    dup_src = (
        "import sys\nif sys.platform == 'win32':\n    def test_dup():\n        assert 1 == 1\n"
        "else:\n    def test_dup():\n        assert 2 == 2\n"
    )
    dup_parsed = parse_python(dup_src.encode("utf-8"), collect_tests=True)
    dup_map = source_unit_map(dup_parsed)
    assert [u.qualname for u in dup_parsed.units] == ["test_dup", "test_dup#2"]
    assert resolve_source_unit(dup_map, dup_parsed.units[1].span, type("F", (), {"name": "test_dup"})()) == "test_dup#2"

    # 4. Normalized result table consolidation (`normalized_result_tables._project`).
    norm_prod = "def label(x):\n    return x + ':ok'\n"
    before_norm = (
        "from labels import label\n\n\n"
        "def test_a():\n"
        '    assert label("alpha") == "alpha:ok"\n'
    )
    after_norm = (
        "import pytest\nfrom labels import label\n\n\n"
        '@pytest.mark.parametrize("x, expected, prefix", [("alpha", "alpha:ok", "alpha")])\n'
        "def test_labels(x, expected, prefix):\n"
        "    got = label(x)\n"
        "    assert got.strip().startswith(prefix) == expected.strip().startswith(prefix)\n"
    )
    ir_norm, findings_norm, verdict_norm = _run_mem(
        {"tests/test_labels.py": before_norm},
        {"tests/test_labels.py": after_norm},
        base_repo={"labels.py": norm_prod},
    )
    assert any(u.qualname.startswith("test_concrete_") for u in ir_norm.files[0].units)
    assert verdict_norm == "block"
    assert [(f.rule, f.unit) for f in findings_norm if f.unit is not None] == [
        ("EXPECTED_VALUE_CHANGED", "test_labels")
    ]
    assert all("test_concrete_" not in f.fingerprint for f in findings_norm)


def test_synthetic_exception_and_local_auxiliary_units_emit_source_unit_names():
    before_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname="test_exception_deadbeef0001_1",
                span=(10, 40),
                side=UnitSide(
                    span=(10, 40),
                    assertions=[
                        Assertion(
                            id="b0",
                            span=(20, 38),
                            text="pytest.raises(ValueError, match='bad')",
                            form="pattern",
                            strength=70,
                        )
                    ],
                ),
                shingles=frozenset({"s1"}),
                source_unit="TestErrors.test_bad_input",
            ),
            ParsedUnit(
                qualname="test_local_auxiliary_deadbeef0002_1",
                span=(50, 90),
                side=UnitSide(
                    span=(50, 90),
                    assertions=[
                        Assertion(
                            id="b1",
                            span=(60, 88),
                            text="assert check_local(1) == 2",
                            form="compare_eq",
                            strength=90,
                            left="check_local(1)",
                            right_literal="2",
                            right_value="2",
                        )
                    ],
                ),
                shingles=frozenset({"s2"}),
                source_unit="test_local_invariant",
            ),
        ],
    )
    after_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname="test_exception_deadbeef0001_1",
                span=(10, 40),
                side=UnitSide(
                    span=(10, 40),
                    assertions=[
                        Assertion(
                            id="a0",
                            span=(20, 35),
                            text="pytest.raises(ValueError)",
                            form="raises",
                            strength=50,
                        )
                    ],
                ),
                shingles=frozenset({"s1"}),
                source_unit="TestErrors.test_bad_input",
            ),
            ParsedUnit(
                qualname="test_local_auxiliary_deadbeef0002_1",
                span=(50, 90),
                side=UnitSide(
                    span=(50, 90),
                    assertions=[
                        Assertion(
                            id="a1",
                            span=(60, 88),
                            text="assert check_local(1) == 3",
                            form="compare_eq",
                            strength=90,
                            left="check_local(1)",
                            right_literal="3",
                            right_value="3",
                        )
                    ],
                ),
                shingles=frozenset({"s2"}),
                source_unit="test_local_invariant",
            ),
        ],
    )
    file_ir = align_file("tests/test_aux.py", "test", "modified", before_parsed, after_parsed)
    ir = IR(base="base", head="head", files=[file_ir], globals=DiffGlobals())
    findings = [f for det in REGISTRY.values() for f in det(ir)]
    verdict = apply_gates(ir, findings, Contract(), Config(), [], TODAY)
    assert verdict == "block"
    by_rule = {f.rule: f for f in findings}
    assert by_rule["ASSERT_WEAKENED"].unit == "TestErrors.test_bad_input"
    assert by_rule["EXPECTED_VALUE_CHANGED"].unit == "test_local_invariant"
    for f in findings:
        assert "test_exception_" not in f.unit and "test_local_auxiliary_" not in f.unit
        assert "test_exception_" not in f.fingerprint and "test_local_auxiliary_" not in f.fingerprint


def test_gating_isolates_repair_evidence_across_sibling_projected_units():
    # Two projected concrete units share `source_unit="test_rates"`.
    # Unit 1 calls `rate_a` (changed in prod); Unit 2 calls `rate_b` (unchanged).
    # Unit 2's rewritten expectation MUST still block at `high` without
    # inheriting Unit 1's REPAIR_EVIDENCE.
    before_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname="test_concrete_aaaa_1",
                span=(10, 80),
                side=UnitSide(
                    span=(10, 80),
                    calls=("rate_a",),
                    assertions=[
                        Assertion(
                            id="b1",
                            span=(30, 55),
                            text="assert rate_a(1) == 10",
                            form="compare_eq",
                            strength=90,
                            left="rate_a(1)",
                            right_literal="10",
                            right_value="10",
                        )
                    ],
                ),
                shingles=frozenset({"a"}),
                source_unit="test_rates",
            ),
            ParsedUnit(
                qualname="test_concrete_bbbb_1",
                span=(10, 80),
                side=UnitSide(
                    span=(10, 80),
                    calls=("rate_b",),
                    assertions=[
                        Assertion(
                            id="b2",
                            span=(56, 80),
                            text="assert rate_b(1) == 20",
                            form="compare_eq",
                            strength=90,
                            left="rate_b(1)",
                            right_literal="20",
                            right_value="20",
                        )
                    ],
                ),
                shingles=frozenset({"b"}),
                source_unit="test_rates",
            ),
        ],
    )
    after_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname="test_concrete_aaaa_1",
                span=(10, 80),
                side=UnitSide(
                    span=(10, 80),
                    calls=("rate_a",),
                    assertions=[
                        Assertion(
                            id="a1",
                            span=(30, 55),
                            text="assert rate_a(1) == 11",
                            form="compare_eq",
                            strength=90,
                            left="rate_a(1)",
                            right_literal="11",
                            right_value="11",
                        )
                    ],
                ),
                shingles=frozenset({"a"}),
                source_unit="test_rates",
            ),
            ParsedUnit(
                qualname="test_concrete_bbbb_1",
                span=(10, 80),
                side=UnitSide(
                    span=(10, 80),
                    calls=("rate_b",),
                    assertions=[
                        Assertion(
                            id="a2",
                            span=(56, 80),
                            text="assert rate_b(1) == 99",
                            form="compare_eq",
                            strength=90,
                            left="rate_b(1)",
                            right_literal="99",
                            right_value="99",
                        )
                    ],
                ),
                shingles=frozenset({"b"}),
                source_unit="test_rates",
            ),
        ],
    )
    file_ir = align_file("tests/test_rates.py", "test", "modified", before_parsed, after_parsed)
    globals_ir = DiffGlobals(
        prod_files_changed=["app/rates.py"],
        prod_symbols_changed=["app.rates::rate_a"],
        test_file_imports={"tests/test_rates.py": ["app.rates"]},
    )
    ir = IR(base="base", head="head", files=[file_ir], globals=globals_ir)
    findings = [f for det in REGISTRY.values() for f in det(ir)]
    verdict = apply_gates(ir, findings, Contract(), Config(), [], TODAY)

    assert verdict == "block"
    assert len(findings) == 2
    assert all(f.unit == "test_rates" for f in findings)
    by_after = {f.after.text: f for f in findings if f.after is not None}
    assert by_after["assert rate_a(1) == 11"].severity == "warn"
    assert "REPAIR_EVIDENCE" in by_after["assert rate_a(1) == 11"].deescalators
    assert by_after["assert rate_b(1) == 99"].severity == "high"
    assert "PROD_CHANGE_NOT_EVIDENCE" in by_after["assert rate_b(1) == 99"].escalators

    # Sibling TOLERANCE_LOOSENED findings sharing identical `rel=1e-6 -> rel=1e-2`
    # Evidence spans/texts resolve to their exact concrete Unit (`rate_a` gets
    # `REPAIR_EVIDENCE_REFUSED`; `rate_b` gets `PROD_CHANGE_NOT_EVIDENCE`).
    from dataclasses import replace

    tol_b = parse_python(
        (
            "import pytest\n"
            "def test_concrete_tol_rate_a():\n"
            "    assert rate_a(1) == pytest.approx(10.0, rel=1e-6)\n"
            "def test_concrete_tol_rate_b():\n"
            "    assert rate_b(1) == pytest.approx(10.0, rel=1e-6)\n"
        ).encode("utf-8"),
        collect_tests=True,
    )
    tol_a = parse_python(
        (
            "import pytest\n"
            "def test_concrete_tol_rate_a():\n"
            "    assert rate_a(1) == pytest.approx(10.0, rel=1e-2)\n"
            "def test_concrete_tol_rate_b():\n"
            "    assert rate_b(1) == pytest.approx(10.0, rel=1e-2)\n"
        ).encode("utf-8"),
        collect_tests=True,
    )
    tol_before = replace(
        tol_b,
        units=[
            replace(u, span=(10, 80), side=replace(u.side, span=(10, 80)), source_unit="test_rates")
            for u in tol_b.units
        ],
    )
    tol_after = replace(
        tol_a,
        units=[
            replace(u, span=(10, 80), side=replace(u.side, span=(10, 80)), source_unit="test_rates")
            for u in tol_a.units
        ],
    )
    tol_file = align_file("tests/test_rates.py", "test", "modified", tol_before, tol_after)
    tol_ir = IR(base="base", head="head", files=[tol_file], globals=globals_ir)
    tol_findings = [f for det in REGISTRY.values() for f in det(tol_ir)]
    tol_verdict = apply_gates(tol_ir, tol_findings, Contract(), Config(), [], TODAY)
    assert tol_verdict == "block"
    assert len(tol_findings) == 2
    assert all(f.rule == "TOLERANCE_LOOSENED" and f.unit == "test_rates" for f in tol_findings)
    assert tol_findings[0].escalators != tol_findings[1].escalators
    assert {"REPAIR_EVIDENCE_REFUSED", "PROD_CHANGE_NOT_EVIDENCE"} <= {
        esc for f in tol_findings for esc in f.escalators
    }


def test_duplicate_projected_assertions_and_removed_units_have_distinct_fingerprints():
    # 1. Duplicate concrete assertions in one `source_unit` both rewritten get
    #    distinct v2 fingerprints via `unit_assertion_position` `(0, 2)` vs `(1, 2)`.
    before_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname=f"test_concrete_dup_{idx}",
                span=(10, 90),
                side=UnitSide(
                    span=(10, 90),
                    assertions=[
                        Assertion(
                            id=f"b{idx}",
                            span=(20 + idx * 30, 45 + idx * 30),
                            text="assert rate(1) == 10",
                            form="compare_eq",
                            strength=90,
                            left="rate(1)",
                            right_literal="10",
                            right_value="10",
                        )
                    ],
                ),
                shingles=frozenset({f"r{idx}"}),
                source_unit="test_rates",
            )
            for idx in (1, 2)
        ],
    )
    after_parsed = ParsedFile(
        parse_ok=True,
        units=[
            ParsedUnit(
                qualname=f"test_concrete_dup_{idx}",
                span=(10, 90),
                side=UnitSide(
                    span=(10, 90),
                    assertions=[
                        Assertion(
                            id=f"a{idx}",
                            span=(20 + idx * 30, 45 + idx * 30),
                            text="assert rate(1) == 99",
                            form="compare_eq",
                            strength=90,
                            left="rate(1)",
                            right_literal="99",
                            right_value="99",
                        )
                    ],
                ),
                shingles=frozenset({f"r{idx}"}),
                source_unit="test_rates",
            )
            for idx in (1, 2)
        ],
    )
    file_ir = align_file("tests/test_dup_rows.py", "test", "modified", before_parsed, after_parsed)
    ir = IR(base="base", head="head", files=[file_ir], globals=DiffGlobals())
    findings = [f for det in REGISTRY.values() for f in det(ir)]
    assert len(findings) == 2
    assert findings[0].unit == findings[1].unit == "test_rates"
    assert findings[0].fingerprint != findings[1].fingerprint

    allow_first = [
        AllowEntry(
            fingerprint=findings[0].fingerprint,
            rule="EXPECTED_VALUE_CHANGED",
            reason="exempt first duplicate row only",
            author="test",
            created="2026-11-14",
            expires="2027-01-01",
        )
    ]
    findings_allow = [f for det in REGISTRY.values() for f in det(ir)]
    verdict = apply_gates(ir, findings_allow, Contract(), Config(), allow_first, TODAY)
    assert verdict == "block"
    assert [f.allowlisted for f in findings_allow] == [True, False]

    # 2. Duplicate disappeared projected units sharing `source_unit` get distinct
    #    TEST_DISABLED `unit_removed` fingerprints.
    removed_ir = align_file(
        "tests/test_dup_rows.py",
        "test",
        "modified",
        before_parsed,
        ParsedFile(parse_ok=True, units=[]),
    )
    ir_rem = IR(base="base", head="head", files=[removed_ir], globals=DiffGlobals())
    rem_findings = [f for det in REGISTRY.values() for f in det(ir_rem) if f.rule == "TEST_DISABLED"]
    assert len(rem_findings) == 2
    assert rem_findings[0].unit == rem_findings[1].unit == "test_rates"
    assert rem_findings[0].fingerprint != rem_findings[1].fingerprint


def test_cli_formats_schema_and_ir_roundtrip_use_real_test_names(tmp_path: Path):
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (tmp_path / "billing.py").write_text(BILLING_PY, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_billing.py").write_text(
        "from billing import apply_discount\n\n\n"
        "def test_first():\n"
        "    assert apply_discount(200.0, 25) == 150.0\n\n\n"
        "def test_second():\n"
        "    assert apply_discount(100.0, 10) == 90.0\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-q", "-m", "base")

    (tmp_path / "tests" / "test_billing.py").write_text(
        "from billing import apply_discount\n\n\n"
        "def test_discounts():\n"
        "    for total, pct, want in [(200.0, 25, 150.0), (100.0, 10, 95.0)]:\n"
        "        assert apply_discount(total, pct) == want\n",
        encoding="utf-8",
    )
    git("commit", "-q", "-a", "-m", "consolidate with expectation edit")

    def run_cli(*args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["check", "HEAD~1..HEAD", "--repo", str(tmp_path), *args])
        return code, out.getvalue(), err.getvalue()

    code_term, out_term, _ = run_cli("--format", "term")
    assert code_term == 1
    assert "tests/test_billing.py :: test_discounts" in out_term
    assert "test_concrete_" not in out_term

    code_json, out_json, _ = run_cli("--format", "json")
    assert code_json == 1
    payload = json.loads(out_json)
    schema_spec = importlib.util.spec_from_file_location(
        "_test_findings_schema",
        Path(__file__).with_name("test_findings_schema.py"),
    )
    assert schema_spec is not None and schema_spec.loader is not None
    schema_mod = importlib.util.module_from_spec(schema_spec)
    schema_spec.loader.exec_module(schema_mod)
    schema = schema_mod._schema()
    assert schema_mod._errors(payload, schema, schema) == []
    assert payload["verdict"] == "block"
    assert len(payload["findings"]) == 1
    jf = payload["findings"][0]
    assert jf["unit"] == "test_discounts"
    assert "test_concrete_" not in out_json

    code_sarif, out_sarif, _ = run_cli("--format", "sarif")
    assert code_sarif == 1
    assert "test_discounts" in out_sarif
    assert "test_concrete_" not in out_sarif

    code_hook, out_hook, _ = run_cli("--format", "hook-json")
    assert code_hook == 0
    # Range mode is not Stop mode; check worktree hook-json by resetting soft to base.
    git("reset", "--soft", "HEAD~1")
    out_stop, err_stop = io.StringIO(), io.StringIO()
    with redirect_stdout(out_stop), redirect_stderr(err_stop):
        code_stop = cli.main(["check", "--format", "hook-json", "--repo", str(tmp_path)])
    assert code_stop == 0
    stop_payload = json.loads(out_stop.getvalue())
    assert stop_payload["decision"] == "block"
    assert "test_discounts" in stop_payload["reason"]
    assert "test_concrete_" not in stop_payload["reason"]
    git("commit", "-q", "-m", "restore head")

    code_ir, out_ir, _ = run_cli("--emit-ir")
    assert code_ir == 0
    ir_data = json.loads(out_ir)
    test_units = ir_data["files"][0]["units"]
    assert any(u["qualname"].startswith("test_concrete_") for u in test_units)
    for u in test_units:
        assert u["source_unit"] == "test_discounts"
        reconstructed = Unit(
            kind=u["kind"],
            qualname=u["qualname"],
            match=u["match"],
            before=None,
            after=None,
            delta=None,
            source_unit=u["source_unit"],
        )
        assert to_jsonable(reconstructed)["source_unit"] == u["source_unit"]
