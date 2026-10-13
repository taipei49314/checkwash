"""Proposed literal catch-oracle labels; remote execution remains pending.

The owned Vitest source pair is reused byte for byte. Existing #363 fixtures,
severity policy, assertion identity and unknown-predicate behavior stay intact.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript


HEADER = 'import { expect, it } from "vitest";\n'
ORACLE = "expect(value()).toBe(1);"


def source(body: str, extra: str = "") -> bytes:
    return (HEADER + extra + '\nit("value", () => {\n' + body + "\n});\n").encode()


def parsed_catch(body: str, extra: str = ""):
    return parse_javascript(source("try { " + ORACLE + " } catch (error) { " + body + " }", extra))


@pytest.mark.parametrize("case_id,verdict,rules", [
    ("JS-CATCH-TAUTOLOGY", "block", [("BROAD_EXCEPT_ADDED", "high")]),
    ("JS-CATCH-RETHROW", "pass", []),
])
def test_native_verified_owned_pair_keeps_its_original_source(case_id, verdict, rules):
    catalog = json.loads((Path(__file__).resolve().parents[1] / "tools/js_obligation_pairs.json")
                         .read_text(encoding="utf-8"))
    case, = [case for case in catalog["cases"] if case["id"] == case_id]
    pair = case["files"]["value.test.ts"]
    _ir, findings, actual = analyze(
        [FileChange("value.test.ts", "modified", pair["before"].encode(), pair["after"].encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 12),
    )
    assert actual == verdict
    assert [(finding.rule, finding.severity) for finding in findings] == rules


@pytest.mark.parametrize("assertion", [
    "expect(true).toBe(true);",
    "expect(false).toBe(false);",
    "expect(null).toBe(null);",
    "expect(true).not.toBe(false);",
    "expect(false).not.toBe(true);",
    "expect(null).not.toBe(true);",
    "expect(true).toBeTruthy();",
    "expect(false).toBeFalsy();",
    "expect(null).toBeFalsy();",
    "expect(false).not.toBeTruthy();",
    "expect(true).not.toBeFalsy();",
    "expect(null).toBeNull();",
    "expect(true).not.toBeNull();",
    "expect(false).toBeDefined();",
    "expect(null).not.toBeUndefined();",
    "expect((/* subject */ true)).toBe((true));",
])
def test_proved_passing_literal_cannot_replace_a_caught_failure(assertion):
    parsed = parsed_catch(assertion)
    assert parsed.swallowing_handlers == ("catch assertion",)
    # The new handler evidence does not relabel, remove or weaken the IR oracle.
    guarded, caught = parsed.units[0].side.assertions
    assert guarded.left == "value()"
    assert caught.trivial is False
    assert caught.form != "tautology"


@pytest.mark.parametrize("imports,assertion", [
    ('import { expect as check } from "vitest";', "check(true).toBe(true);"),
    ('import { expect as check } from "@jest/globals";', "check(false).toBeFalsy();"),
    ('import assert from "node:assert";', "assert(true);"),
    ('import assert from "node:assert";', "assert.ok(true);"),
    ('import assert from "node:assert";', "assert.strictEqual(false, false);"),
    ('import assert from "node:assert/strict";', "assert.equal(null, null);"),
    ('import { strictEqual as verify } from "node:assert";', "verify(true, true);"),
    ('import { assert } from "chai";', "assert.isTrue(true);"),
    ('import { assert } from "chai";', "assert.isFalse(false);"),
    ('import { assert } from "chai";', "assert.isNull(null);"),
    ('import { assert } from "chai";', "assert.isDefined(true);"),
    ('import { assert } from "chai";', "assert.strictEqual(true, true);"),
])
def test_resolved_direct_api_identity_is_reused(imports, assertion):
    assert parsed_catch(assertion, imports).swallowing_handlers == ("catch assertion",)


@pytest.mark.parametrize("assertion", [
    "expect(true).toBe(false);",
    "expect(false).toBeTruthy();",
    "expect(true).toBeFalsy();",
    "expect(true).not.toBe(true);",
    "expect(null).not.toBeNull();",
    "expect(false).toBeUndefined();",
    "expect(error.message).toMatch(/invalid/);",
    "expect(error.code).toBe(1);",
])
def test_failing_or_actual_error_inspection_still_preserves_failure(assertion):
    assert parsed_catch(assertion).swallowing_handlers == ()


@pytest.mark.parametrize("body", [
    "const expected = true; expect(expected).toBe(true);",
    "let expected = true; expected = readValue(); expect(expected).toBe(true);",
    "expect(readValue()).toBe(true);",
    "expect(undefined).toBeUndefined();",
    "const undefined = true; expect(undefined).toBeUndefined();",
    "expect(true).toBe(undefined);",
    "const undefined = false; expect(true).toBe(undefined);",
    "expect(true).toEqual(true);",
    "expect(1).toBe(1);",
    "expect('literal').toBe('literal');",
    "expect(true, sideEffect()).toBe(true);",
    "expect(true).toBe(true, sideEffect());",
    "expect(true).toBeTruthy(sideEffect());",
    "expect(true).customMatcher();",
    "expect(false as boolean || true).toBe(false);",
    "expect(false).toBe(false as boolean || true);",
    "expect(true as boolean).toBe(true);",
])
def test_unproved_values_matchers_or_argument_effects_keep_existing_exemption(body):
    assert parsed_catch(body).swallowing_handlers == ()


@pytest.mark.parametrize("body,extra", [
    ("const expect = localExpect; expect(true).toBe(true);", ""),
    ("const assert = localAssert; assert(true);", 'import assert from "node:assert";'),
    ("assert.ok = localAssert; assert.ok(true);", 'import assert from "node:assert";'),
])
def test_shadowed_or_replaced_names_do_not_donate_assertion_authority(body, extra):
    assert parsed_catch(body, extra).swallowing_handlers == ("catch assertion",)


def test_catch_parameter_shadow_does_not_donate_assertion_authority():
    body = "try { " + ORACLE + " } catch (expect) { expect(true).toBe(true); }"
    assert parse_javascript(source(body)).swallowing_handlers == ("catch assertion",)


def test_passing_literal_in_guard_is_still_a_protected_assertion():
    parsed = parse_javascript(source("try { expect(true).toBe(true); } catch {}"))
    assert parsed.swallowing_handlers == ("catch assertion",)
    assert len(parsed.units[0].side.assertions) == 1


@pytest.mark.parametrize("body", [
    "expect(true).toBe(true); throw error;",
    "expect(true).toBe(true); expect(error.message).toMatch(/invalid/);",
    "if (true) { expect(error.code).toBe(1); } expect(true).toBe(true);",
])
def test_other_active_failure_evidence_is_not_cancelled_by_a_literal(body):
    assert parsed_catch(body).swallowing_handlers == ()


@pytest.mark.parametrize("body", [
    "expect(true).toBe(true); return; expect(error.code).toBe(1);",
    "if (true) { expect(true).toBe(true); }",
    "if (false) { expect(error.code).toBe(1); } expect(true).toBe(true);",
])
def test_existing_terminal_and_literal_branch_boundaries_are_retained(body):
    assert parsed_catch(body).swallowing_handlers == ("catch assertion",)


def test_setup_only_try_and_unchanged_handler_do_not_add_findings():
    for before, after in [
        ("setup(); " + ORACLE, "try { setup(); } catch { expect(true).toBe(true); } " + ORACLE),
        ("try { " + ORACLE + " } catch { expect(true).toBe(true); }",) * 2,
    ]:
        _ir, findings, verdict = analyze(
            [FileChange("tests/value.test.ts", "modified", source(before), source(after))],
            Config(), Contract(), [], datetime.date(2026, 10, 12),
        )
        assert verdict == "pass"
        assert findings == []
