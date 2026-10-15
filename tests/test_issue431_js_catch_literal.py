"""Always-passing literal assertions in a JS/TS catch (#431).

A catch whose reachable assertions are all proved to always pass cannot
report the failure it caught. It keeps its own handler text, so main's
"catch assertion" events are unchanged and the two can never offset each
other in the per-file multiset comparison. Anything the narrow proof cannot
read keeps the existing #363 exemption. Expectations are new labels; execute
only through remote CI.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.exception_handlers import ALWAYS_PASSING, SWALLOWED
from checkwash.frontends.javascript.frontend import parse_javascript


HEADER = 'import { expect, it } from "vitest";\n'
ORACLE = "expect(value()).toBe(1);"
OTHER = "expect(other()).toBe(2);"


def source(body: str, extra: str = "") -> bytes:
    return (HEADER + extra + '\nit("value", () => {\n' + body + "\n});\n").encode()


def parsed_catch(body: str, extra: str = ""):
    return parse_javascript(source("try { " + ORACLE + " } catch (error) { " + body + " }", extra))


def shape(assertion):
    return assertion.form, assertion.strength, assertion.trivial, assertion.predicate, assertion.positive


def outcome(before: str, after: str):
    change = FileChange("tests/value.test.ts", "modified", source(before), source(after))
    _ir, findings, verdict = analyze(
        [change], Config(), Contract(), [], datetime.date(2026, 10, 14)
    )
    return verdict, findings


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
    assert parsed.swallowing_handlers == (ALWAYS_PASSING,)
    # The handler evidence does not relabel, remove or weaken the IR oracle:
    # the caught assertion reads exactly as it does outside any try.
    guarded, caught = parsed.units[0].side.assertions
    assert guarded.left == "value()"
    _plain_guarded, plain = parse_javascript(source(ORACLE + " " + assertion)).units[0].side.assertions
    assert shape(caught) == shape(plain)


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
    assert parsed_catch(assertion, imports).swallowing_handlers == (ALWAYS_PASSING,)


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
    # Named residuals in docs/js-catch-swallowing.md, not proofs of safety.
    assert parsed_catch(body).swallowing_handlers == ()


@pytest.mark.parametrize("body,extra", [
    ("const expect = localExpect; expect(true).toBe(true);", ""),
    ("const assert = localAssert; assert(true);", 'import assert from "node:assert";'),
    ("assert.ok = localAssert; assert.ok(true);", 'import assert from "node:assert";'),
])
def test_shadowed_or_replaced_names_do_not_donate_assertion_authority(body, extra):
    assert parsed_catch(body, extra).swallowing_handlers == (SWALLOWED,)


def test_catch_parameter_shadow_does_not_donate_assertion_authority():
    body = "try { " + ORACLE + " } catch (expect) { expect(true).toBe(true); }"
    assert parse_javascript(source(body)).swallowing_handlers == (SWALLOWED,)


def test_passing_literal_in_guard_is_still_a_protected_assertion():
    literal = "expect(true).toBe(true);"
    parsed = parse_javascript(source("try { " + literal + " } catch {}"))
    assert parsed.swallowing_handlers == (SWALLOWED,)
    guarded, = parsed.units[0].side.assertions
    plain, = parse_javascript(source(literal)).units[0].side.assertions
    assert shape(guarded) == shape(plain)


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
    assert parsed_catch(body).swallowing_handlers == (ALWAYS_PASSING,)


def test_setup_only_try_and_unchanged_handler_do_not_add_findings():
    literal_catch = "try { " + ORACLE + " } catch (error) { expect(true).toBe(true); }"
    for before, after in [
        ("setup(); " + ORACLE, "try { setup(); } catch { expect(true).toBe(true); } " + ORACLE),
        (literal_catch, literal_catch),
        (literal_catch, "try {\n  " + ORACLE + "\n} catch (e) {\n  expect(true).toBe(true);\n}"),
    ]:
        verdict, findings = outcome(before, after)
        assert verdict == "pass"
        assert findings == []


def test_issue_pair_reports_the_always_passing_text():
    verdict, findings = outcome(
        ORACLE, "try { " + ORACLE + " } catch (error) { expect(true).toBe(true); }"
    )
    assert verdict == "block"
    assert [(f.rule, f.severity, f.after.text) for f in findings] == [
        ("BROAD_EXCEPT_ADDED", "high", ALWAYS_PASSING)
    ]
    assert findings[0].message == f"broad exception handler added ({ALWAYS_PASSING})"


LITERAL = "expect(true).toBe(true);"


@pytest.mark.parametrize("before,after,text", [
    # An existing literal-only catch is repaired while a new swallowing
    # catch is added in the same file. A single shared text would net the
    # two to zero; main blocks this, and so must the fix.
    ("try { " + ORACLE + " } catch (error) { " + LITERAL + " } " + OTHER,
     "try { " + ORACLE + " } catch (error) { " + LITERAL + " throw error; } try { " + OTHER + " } catch {}",
     SWALLOWED),
    # The mirror: an old empty swallow repaired, a new literal-only catch added.
    ("try { " + ORACLE + " } catch {} " + OTHER,
     "try { " + ORACLE + " } catch (error) { throw error; } try { " + OTHER + " } catch (error) { " + LITERAL + " }",
     ALWAYS_PASSING),
    # Adding an always-passing literal to a catch that already swallows is
    # reported (the ruled cost of a separate text).
    ("try { " + ORACLE + " } catch {}",
     "try { " + ORACLE + " } catch { " + LITERAL + " }",
     ALWAYS_PASSING),
], ids=["repaired-literal-catch-cannot-pay", "repaired-empty-catch-cannot-pay", "literal-added-to-swallow"])
def test_literal_only_catches_do_not_offset_swallowing_catches(before, after, text):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert [(f.rule, f.severity, f.after.text) for f in findings] == [("BROAD_EXCEPT_ADDED", "high", text)]


def test_removing_the_literal_from_a_catch_still_reports_the_swallow():
    verdict, findings = outcome(
        "try { " + ORACLE + " } catch { " + LITERAL + " }",
        "try { " + ORACLE + " } catch {}",
    )
    assert verdict == "block"
    assert ("BROAD_EXCEPT_ADDED", "high", SWALLOWED) in [
        (f.rule, f.severity, f.after.text) for f in findings if f.after is not None
    ]
