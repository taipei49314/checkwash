"""Bounded synchronous assertion swallowing in JS/TS test callbacks (#363).

Expectations are new label proposals pending maintainer review. Execute only
through remote CI; the work machine must not run this module.
"""

from __future__ import annotations

import datetime
import statistics
import time

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript

HEAD = 'import { expect, it } from "vitest";\n'
ORACLE = "expect(withTax(10.005, 0.1)).toBe(11.01);"


def source(body: str) -> bytes:
    return (HEAD + 'it("rounds to cents", () => {\n' + body + "\n});\n").encode()


def outcome(before: str, after: str, path: str = "tests/cart.test.ts"):
    change = FileChange(path, "modified", source(before), source(after))
    _ir, findings, verdict = analyze(
        [change], Config(), Contract(), [], datetime.date(2026, 10, 11)
    )
    return verdict, [(finding.rule, finding.severity) for finding in findings]


@pytest.mark.parametrize("handler", [
    "catch (e) {}",
    "catch (e) { /* rounding differs between CI runners */ }",
    "catch {}",
    "catch (e) { return; }",
    "catch (e) { console.log(e); }",
])
def test_wrapping_an_unchanged_synchronous_assertion_blocks(handler):
    assert outcome(ORACLE, "try { " + ORACLE + " } " + handler) == (
        "block", [("BROAD_EXCEPT_ADDED", "high")]
    )


@pytest.mark.parametrize("handler", [
    "catch (e) { throw e; }",
    "catch (e) { throw new Error('failure'); }",
    "catch (e) { expect(e.message).toMatch(/invalid/); }",
])
def test_rethrow_or_active_assertion_is_not_swallowing(handler):
    parsed = parse_javascript(source("try { " + ORACLE + " } " + handler))
    assert parsed.swallowing_handlers == ()


def test_setup_only_try_does_not_wrap_the_assertion_after_it():
    assert outcome("setup(); " + ORACLE, "try { setup(); } catch {} " + ORACLE) == (
        "pass", []
    )


def test_unchanged_swallowing_handler_is_not_added():
    body = "try { " + ORACLE + " } catch {}"
    assert outcome(body, body) == ("pass", [])


def test_handler_formatting_and_binding_rename_are_not_an_addition():
    assert outcome(
        "try { " + ORACLE + " } catch (e) {}",
        "try {\n" + ORACLE + "\n} catch (error) { /* unchanged */ }",
    ) == ("pass", [])


def test_removing_a_rethrow_is_an_addition_without_a_new_catch_header():
    assert outcome(
        "try { " + ORACLE + " } catch (e) { throw e; }",
        "try { " + ORACLE + " } catch (e) {}",
    ) == ("block", [("BROAD_EXCEPT_ADDED", "high")])


@pytest.mark.parametrize("body", [
    "try { const unused = () => { " + ORACLE + " }; } catch {}",
    "try { register(() => { " + ORACLE + " }); } catch {}",
    "try { return; " + ORACLE + " } catch {}",
    "try { if (false) { " + ORACLE + " } } catch {}",
])
def test_nested_or_unreachable_assertion_does_not_donate_to_outer_try(body):
    assert parse_javascript(source(body)).swallowing_handlers == ()


@pytest.mark.parametrize("handler", [
    "catch (e) { const unused = () => { throw e; }; }",
    "catch (e) { const unused = () => { expect(e).toBeDefined(); }; }",
    "catch (e) { return; throw e; }",
    "catch (e) { if (false) { throw e; } }",
    "catch (expect) { expect('ignored').toBeDefined(); }",
])
def test_nested_dead_or_shadowed_catch_control_does_not_preserve_failure(handler):
    parsed = parse_javascript(source("try { " + ORACLE + " } " + handler))
    assert len(parsed.swallowing_handlers) == 1


def test_local_catch_inside_an_inline_callback_is_read():
    body = "rows.forEach(() => { try { " + ORACLE + " } catch {} });"
    assert len(parse_javascript(source(body)).swallowing_handlers) == 1


def test_async_callback_still_catches_a_synchronous_matcher_locally():
    text = HEAD + 'it("rounds", async () => { try { ' + ORACLE + " } catch {} });"
    assert len(parse_javascript(text.encode()).swallowing_handlers) == 1


@pytest.mark.parametrize("oracle", [
    "expect(value).resolves.toBe(1);",
    "expect(value).rejects.toThrow();",
])
def test_promise_completion_is_outside_this_synchronous_channel(oracle):
    assert parse_javascript(source("try { " + oracle + " } catch {}" )).swallowing_handlers == ()


def test_inert_text_is_not_a_handler():
    assert parse_javascript(source("const text = 'try { expect(x).toBe(1) } catch {}'; " + ORACLE)).swallowing_handlers == ()


@pytest.mark.parametrize("oracle", [
    "expect(response.rejects).toBe(false);",
    "expect(message).toBe('client.resolves');",
    "expect(message).toBe('client.rejects');",
])
def test_promise_words_inside_operands_are_synchronous(oracle):
    assert outcome(oracle, "try { " + oracle + " } catch {}") == (
        "block", [("BROAD_EXCEPT_ADDED", "high")]
    )


@pytest.mark.parametrize("oracle", [
    "expect(e.rejects).toBe(false);",
    "expect(e.message).toBe('client.resolves');",
    "expect(e.message).toBe('client.rejects');",
])
def test_promise_words_do_not_erase_active_catch_inspection(oracle):
    assert parse_javascript(source("try { " + ORACLE + " } catch (e) { " + oracle + " }")).swallowing_handlers == ()


@pytest.mark.parametrize("body", [
    "return; try { " + ORACLE + " } catch {}",
    "throw new Error(); try { " + ORACLE + " } catch {}",
    "if (false) { try { " + ORACLE + " } catch {} }",
    "if (true) { return; } try { " + ORACLE + " } catch {}",
    "try { function unused() {} return; " + ORACLE + " } catch {}",
    "try { function unused() {} if (false) { " + ORACLE + " } } catch {}",
])
def test_unreachable_try_or_oracle_has_no_handler_evidence(body):
    assert parse_javascript(source(body)).swallowing_handlers == ()


@pytest.mark.parametrize("declaration", ["function cleanup() {}", "class Cleanup {}", "async function cleanup() {}"])
def test_declaration_does_not_consume_a_following_rethrow(declaration):
    body = "try { " + ORACLE + " } catch (e) { " + declaration + " throw e; }"
    assert parse_javascript(source(body)).swallowing_handlers == ()


@pytest.mark.parametrize("body", [
    "if (true) { try { " + ORACLE + " } catch {} }",
    "if (false) {} else { try { " + ORACLE + " } catch {} }",
    "try { if (true) { " + ORACLE + " } } catch {}",
    "try { " + ORACLE + " } catch (e) { if (false) { throw e; } else { return; } }",
    "try { " + ORACLE + " } catch (e) { return\nthrow e; }",
])
def test_supported_literal_branches_and_asi_keep_the_local_obligation(body):
    assert len(parse_javascript(source(body)).swallowing_handlers) == 1


@pytest.mark.parametrize("oracle", [
    "expect(value). /* outside the subject */ resolves.toBe(1);",
    "expect(value).\nrejects.toThrow();",
    "expect(value).eventually.equal(1);",
])
def test_structural_promise_chains_are_excluded(oracle):
    assert parse_javascript(source("try { " + oracle + " } catch {}")).swallowing_handlers == ()


@pytest.mark.parametrize("imports, runner, oracle", [
    ('import assert from "node:assert";', 'it("x", () =>', 'assert.doesNotReject(operation);'),
    ('import { rejects as verifyRejects } from "node:assert";', 'it("x", () =>', 'verifyRejects(operation);'),
    ('import test from "ava";', 'test("x", t =>', 't.throwsAsync(operation);'),
    ('import test from "ava";', 'test("x", t =>', 't.notThrowsAsync(operation);'),
    ('import tap from "tap";', 'tap.test("x", t =>', 't.resolveMatch(operation, expected);'),
    ('import tap from "tap";', 'tap.test("x", t =>', 't.rejects(operation);'),
])
def test_resolved_async_apis_do_not_supply_synchronous_evidence(imports, runner, oracle):
    text = HEAD + imports + "\n" + runner + " { try { " + oracle + " } catch {} });"
    assert parse_javascript(text.encode()).swallowing_handlers == ()


@pytest.mark.parametrize("imports, runner, oracle", [
    ('import assert from "node:assert";', 'it("x", () =>', "assert.strictEqual(message, 'client.rejects');"),
    ('import { assert } from "chai";', 'it("x", () =>', 'assert.equal(actual, expected);'),
    ('import test from "ava";', 'test("x", t =>', 't.is(actual, expected);'),
    ('import tap from "tap";', 'tap.test("x", t =>', 't.equal(actual, expected);'),
    ('', 'it("x", () =>', 'expect(spy).toHaveBeenCalledWith(1);'),
])
def test_existing_synchronous_families_and_null_strength_candidates(imports, runner, oracle):
    text = HEAD + imports + "\n" + runner + " { try { " + oracle + " } catch {} });"
    assert len(parse_javascript(text.encode()).swallowing_handlers) == 1


@pytest.mark.parametrize("body", [
    "try { if (flag) { " + ORACLE + " } } catch {}",
    "try { " + ORACLE + " } catch (e) { if (flag) { throw e; } }",
    "try { " + ORACLE + " } catch {} finally {}",
    "try { for (const row of rows) { " + ORACLE + " } } catch {}",
    "try { flag && " + ORACLE + " } catch {}",
    "try { " + ORACLE + " } catch (e) { error?.report(); }",
    "try { await expect(value).resolves.toBe(1); } catch {}",
])
def test_named_unsupported_shapes_supply_no_handler_claim(body):
    assert parse_javascript(source(body)).swallowing_handlers == ()


@pytest.mark.parametrize("dead", [False, True])
def test_deep_balanced_input_is_safe_and_explicitly_outside_depth_coverage(dead):
    nested = "{ " * 1500 + ORACLE + " }" * 1500
    body = "try { " + ("if (false) { " + nested + " }" if dead else nested) + " } catch {}"
    assert parse_javascript(source(body)).swallowing_handlers == ()


def test_nested_inline_callback_scaling_remains_bounded():
    def nested(depth):
        body = ORACLE
        for _index in range(depth):
            body = "try { register(() => { " + body + " }); " + ORACLE + " } catch {}"
        return source(body)

    def median(data, expected):
        samples = []
        for _repeat in range(3):
            started = time.perf_counter()
            parsed = parse_javascript(data)
            samples.append(time.perf_counter() - started)
            assert len(parsed.swallowing_handlers) == expected
        return statistics.median(samples)

    small = median(nested(20), 20)
    large = median(nested(80), 80)
    # Four times the input should not restore a quadratic descendant scan.
    # This generous ratio is a remote regression budget, not a throughput claim.
    assert large < max(small, 0.001) * 10, (small, large)


@pytest.mark.parametrize("body", [
    "try { " + ORACLE + " } catch (e) { function unused(): { value: number } { return { value: 1 }; } throw e; }",
    "try { function unused(): { value: number } { return { value: 1 }; } " + ORACLE + " } catch {}",
    "try { function unused(): { value: number } { try { " + ORACLE + " } catch {} return { value: 1 }; } } catch {}",
    "try { " + ORACLE + " } catch (e) { rethrow: throw e; }",
    "try { " + ORACLE + " } catch (e) { rethrow: { throw e; } }",
    "try { done: { break done; " + ORACLE + " } } catch {}",
])
def test_unsupported_typed_declarations_and_labels_cannot_donate_or_hide_failure(body):
    assert parse_javascript(source(body)).swallowing_handlers == ()


def test_simple_typed_arrow_body_remains_a_function_boundary():
    text = HEAD + 'it("x", (): number => { try { ' + ORACLE + " } catch {} return 1; });"
    assert len(parse_javascript(text.encode()).swallowing_handlers) == 1


@pytest.mark.parametrize("oracle", [
    "order.paid.should.be.true;",
    "e.message.should.exist;",
    "(e.code).should.equal('ERR');",
    "errors[0].should.equal(e);",
    "new Date(0).getTime().should.equal(0);",
])
def test_represented_should_getters_work_in_guard_and_catch(oracle):
    imports = 'import { should } from "chai"; should();\n'
    guarded = imports.encode() + source("try { " + oracle + " } catch {}")
    caught = imports.encode() + source("try { " + ORACLE + " } catch (e) { " + oracle + " }")
    assert len(parse_javascript(guarded).swallowing_handlers) == 1
    assert parse_javascript(caught).swallowing_handlers == ()


@pytest.mark.parametrize("oracle", [
    "result.should.eventually.equal(1);",
    "(result).should.eventually.equal(1);",
    "results[0].should.eventually.equal(1);",
])
def test_should_promise_chain_does_not_supply_a_synchronous_oracle(oracle):
    imports = 'import { should } from "chai"; should();\n'
    assert parse_javascript(imports.encode() + source("try { " + oracle + " } catch {}")).swallowing_handlers == ()


def test_parent_callback_registration_is_a_named_cross_function_residual():
    # The frontend records inline callback obligations lexically. This channel
    # reads each owning body but does not prove a parent invokes that callback.
    body = "return; rows.forEach(() => { try { " + ORACLE + " } catch {} });"
    assert len(parse_javascript(source(body)).swallowing_handlers) == 1
