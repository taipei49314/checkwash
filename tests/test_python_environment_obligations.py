"""Proposed finite labels; no local execution or native label acceptance."""
import datetime
import json
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.assert_weakened import detect
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python import environment_obligations
from checkwash.ir.model import Assertion, to_jsonable
from checkwash.report.jsonout import ir_to_json

PATH = "tests/test_total.py"
ORACLE = "assert total() == 3"
GUARD = 'os.environ.get("CW_RUN_TOTAL") == "1"'
HEADER = "import os\n\ndef total():\n    return 2\n\ndef test_total():\n"


def source(body, header=HEADER):
    return (header + body + "\n").encode()


def outcome(before, after):
    return analyze([FileChange(PATH, "modified", before, after)],
                   Config(), Contract(), [], datetime.date(2026, 10, 13))


@pytest.mark.parametrize("case,verdict", [
    ("PYENVWRAP", "block"), ("PYENVRETURN", "block"),
    ("PYENV_BOTH_BRANCHES", "pass"),
])
def test_fixed_owned_inputs_proposed_obligation_labels(case, verdict):
    root = Path(__file__).resolve().parents[1] / "tools/owned_env_evidence/fixtures" / case
    before = (root / "before" / PATH).read_bytes()
    after = (root / "after" / PATH).read_bytes()
    ir, findings, actual = outcome(before, after)
    assert actual == verdict
    if verdict == "pass":
        assert findings == []
        return
    finding, = findings
    assert (finding.rule, finding.severity) == ("ASSERT_WEAKENED", "high")
    assert finding.before.text == ORACLE
    normalized = after.decode().replace("\r\n", "\n")
    assert normalized[slice(*finding.after.span)] == finding.after.text
    assert 'os.environ.get("CW_RUN_TOTAL")' in finding.after.text
    raw, = detect(ir)
    assert raw.severity == "warn"
    assert raw.strength_after is None
    assert "NO_PROD_CHANGE_IN_DIFF" in finding.escalators


@pytest.mark.parametrize("body", [
    "    " + ORACLE,
    "    " + ORACLE + "\n    return",
    "    " + ORACLE + "\n    if " + GUARD + ":\n        return",
    "    if " + GUARD + ":\n        " + ORACLE + "\n    else:\n        " + ORACLE,
    "    if " + GUARD + ":\n        " + ORACLE + "\n    " + ORACLE,
    "    " + ORACLE + "\n    if " + GUARD + ":\n        " + ORACLE,
])
def test_preserved_validation_path_is_a_normal_control(body):
    _ir, findings, verdict = outcome(source("    " + ORACLE), source(body))
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("guard", [GUARD, 'os.environ.get("CW_RUN_TOTAL") != "1"',
                                    'sys.platform == "linux"'])
def test_existing_guard_is_not_a_new_obligation_loss(guard):
    body = "    if " + guard + ":\n        " + ORACLE
    _ir, findings, verdict = outcome(source(body), source(body + "\n        pass"))
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("body,header", [
    ("    if flag:\n        " + ORACLE, HEADER),
    ("    if " + GUARD + ":\n        if flag:\n            " + ORACLE, HEADER),
    ("    if helper():\n        " + ORACLE, HEADER),
    ("    if " + GUARD + ":\n        " + ORACLE, HEADER.replace("import os", "import fake as os")),
    ("    os = fake\n    if " + GUARD + ":\n        " + ORACLE, HEADER),
    ("    if " + GUARD + ":\n        " + ORACLE, HEADER.replace("import os", "import os as env")),
    ("    if " + GUARD + ":\n        " + ORACLE, HEADER.replace("import os", "from fake import *\nimport os")),
    ("    os.environ.clear()\n    if " + GUARD + ":\n        " + ORACLE, HEADER),
])
def test_unknown_proofs_remain_explicitly_outside_this_finite_package(body, header):
    parsed = parse_python(source(body, header))
    assert all(not assertion.environment_guard for unit in parsed.units for assertion in unit.side.assertions)


def test_preexisting_arbitrary_condition_is_not_unconditional_baseline():
    before = source("    if flag:\n        " + ORACLE)
    after = source("    if " + GUARD + ":\n        " + ORACLE)
    ir, _findings, _verdict = outcome(before, after)
    assert detect(ir) == []


def test_no_old_assertion_obligation_is_invented_for_new_test():
    _ir, findings, verdict = outcome(source("    pass"), source("    if " + GUARD + ":\n        " + ORACLE))
    assert verdict == "pass"
    assert findings == []


def test_direct_return_existing_removal_path_is_preserved():
    _ir, findings, verdict = outcome(source("    " + ORACLE), source("    return\n    " + ORACLE))
    assert verdict == "block"
    assert [finding.rule for finding in findings] == ["ASSERT_REMOVED"]


def test_interposed_binding_does_not_supply_complementary_obligation_credit():
    parsed = parse_python(source("    if " + GUARD + ":\n        " + ORACLE
                                 + "\n    other = total\n    " + ORACLE))
    unit, = parsed.units
    guarded, direct = unit.side.assertions
    assert guarded.environment_guard == GUARD
    assert direct.unconditional_obligation


@pytest.mark.parametrize("barrier", [
    "    def total():\n        return 3",
    "    async def total():\n        return 3",
    "    class total:\n        pass",
    "    mutate_inputs()",
])
@pytest.mark.parametrize("direct_first", [True, False])
def test_definition_and_effectful_call_break_outside_assertion_credit(barrier, direct_first):
    # Source-proof controls only: a local def after an earlier total() can
    # change native name binding. This does not claim that program executes.
    direct = "    " + ORACLE
    guarded = "    if " + GUARD + ":\n        " + ORACLE
    body = direct + "\n" + barrier + "\n" + guarded if direct_first else (
        guarded + "\n" + barrier + "\n" + direct)
    parsed = parse_python(source(body))
    unit, = parsed.units
    assertions = unit.side.assertions
    protected = assertions[1] if direct_first else assertions[0]
    assert protected.environment_guard == GUARD
    assert not protected.unconditional_obligation


@pytest.mark.parametrize("inert", ["    pass", '    "literal note"'])
def test_explicit_inert_statement_preserves_outside_assertion_credit(inert):
    parsed = parse_python(source("    " + ORACLE + "\n" + inert
                                 + "\n    if " + GUARD + ":\n        " + ORACLE))
    unit, = parsed.units
    assert all(assertion.unconditional_obligation for assertion in unit.side.assertions)
    assert all(assertion.environment_guard is None for assertion in unit.side.assertions)


def test_legacy_assertion_payload_uses_unknown_evidence_defaults():
    legacy = {"id": "a0", "form": "compare_eq", "strength": 90,
              "text": ORACLE, "span": [0, len(ORACLE)]}
    assertion = Assertion(**legacy)
    assert not assertion.unconditional_obligation
    assert assertion.environment_guard is None
    assert assertion.environment_guard_span is None
    serialized = to_jsonable(assertion)
    assert serialized["unconditional_obligation"] is False
    assert serialized["environment_guard"] is None
    assert serialized["environment_guard_span"] is None


def test_emit_ir_additive_guard_fields_have_explicit_json_types():
    before = source("    " + ORACLE)
    after = source("    if " + GUARD + ":\n        " + ORACLE)
    ir, _findings, _verdict = outcome(before, after)
    payload = json.loads(ir_to_json(ir))
    unit, = payload["files"][0]["units"]
    old, = unit["before"]["assertions"]
    new, = unit["after"]["assertions"]
    assert old["unconditional_obligation"] is True
    assert old["environment_guard"] is None
    assert old["environment_guard_span"] is None
    assert new["unconditional_obligation"] is False
    assert new["environment_guard"] == GUARD
    span = new["environment_guard_span"]
    assert isinstance(span, list) and len(span) == 2
    assert all(type(offset) is int for offset in span)
    normalized = after.decode().replace("\r\n", "\n")
    assert normalized[slice(*span)] == GUARD


def test_deep_ordinary_assertion_never_adds_a_structural_dump(monkeypatch):
    def forbidden_dump(_node):
        raise AssertionError("ordinary assertion must not request credit key")

    monkeypatch.setattr(environment_obligations, "stable_dump", forbidden_dump)
    expression = "check(" + " + ".join(["value"] * 350) + ")"
    parsed = parse_python(source("    assert " + expression))
    assert parsed.parse_ok
    unit, = parsed.units
    assertion, = unit.side.assertions
    assert assertion.text == "assert " + expression
    assert assertion.unconditional_obligation
    assert assertion.environment_guard is None


def test_deep_guarded_complementary_credit_uses_existing_safe_key():
    expression = "check(" + " + ".join(["value"] * 350) + ")"
    assertion = "assert " + expression
    parsed = parse_python(source("    if " + GUARD + ":\n        " + assertion
                                 + "\n    else:\n        " + assertion))
    assert parsed.parse_ok
    unit, = parsed.units
    assert len(unit.side.assertions) == 2
    assert all(item.text == assertion for item in unit.side.assertions)
    assert all(item.unconditional_obligation for item in unit.side.assertions)
    assert all(item.environment_guard is None for item in unit.side.assertions)
