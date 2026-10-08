"""JS assertions checkwash does not read, recorded with no strength (#196 190.5).

`assert.throws(fn)`, `expect(spy).toHaveBeenCalledWith(1)` and
`expect(order).to.have.keys("total")` are assertions whose predicate the
scans do not read. Before this round they were coverage notices only, so
deleting one passed. SPEC §3 records such a form with strength null, as
Python records `assertRaises`: its removal is ASSERT_REMOVED, and a rewrite
is not judged. The throw family is `raises`; the rest, and a negated throw
check, are `unknown`.

Only a call to a resolved assertion API is recorded. A lookalike (an import
from another module, a shadowed name, a written member) is not: recorded, it
would pair by text with the oracle it replaced. The coverage inventory keeps
its own recognizer, and a recorded call stays a notice there, because its
rewrite is still not judged.
"""

import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript

BLOCK, PASS = "block", "pass"
NODE = 'import { test } from "node:test";\nimport assert from "node:assert";\n'
VITEST = 'import { test, expect, vi } from "vitest";\n'
CHAI = 'import { test } from "node:test";\nimport { expect, assert } from "chai";\n'
JEST_GLOBALS = 'import { test, expect } from "@jest/globals";\n'
VITEST_NODE = 'import { test, expect } from "vitest";\nimport assert from "node:assert";\n'
PATH = "tests/total.test.js"


def _source(body, header):
    return (header + 'import { total, save } from "../src/total.js";\n'
            'test("total", (t) => {\n  const value = total();\n  ' + body + "\n});\n")


def _recorded(body, header):
    units = parse_javascript(_source(body, header).encode()).units
    return [(a.form, a.strength, a.left, a.text) for unit in units for a in unit.side.assertions]


@functools.lru_cache(maxsize=None)
def _outcome(before, after, header):
    changes = [FileChange(PATH, "modified", _source(before, header).encode(), _source(after, header).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 4))
    return verdict, tuple((f.rule, f.severity) for f in findings), tuple(f.message for f in findings)


# --- What is recorded -----------------------------------------------------------------

@pytest.mark.parametrize("body,header,form,left", [
    # node:assert, and the test context's assert.
    ("assert.throws(() => total(-1), RangeError);", NODE, "raises", "() => total(-1)"),
    ("assert.rejects(save());", NODE, "raises", "save()"),
    ("t.assert.rejects(save());", NODE, "raises", "save()"),
    ("assert.doesNotThrow(() => total());", NODE, "unknown", "() => total()"),
    ("assert.doesNotReject(save());", NODE, "unknown", "save()"),
    ("assert.match(String(value), /78/);", NODE, "unknown", "String(value)"),
    ("assert.notStrictEqual(value, 75);", NODE, "unknown", "value"),
    ("assert.ifError(save());", NODE, "unknown", "save()"),
    ("assert.fail('unreachable');", NODE, "unknown", "'unreachable'"),
    ("assert['match'](String(value), /78/);", NODE, "unknown", "String(value)"),
    # Jest and Vitest matchers the scan does not read.
    ("expect(() => total(-1)).toThrow(RangeError);", VITEST, "raises", "() => total(-1)"),
    ("expect(() => total(-1)).toThrowError('negative');", VITEST, "raises", "() => total(-1)"),
    ("expect(save()).rejects.toThrow('closed');", VITEST, "raises", "save()"),
    ("expect(save()).rejects.toBe(1);", VITEST, "raises", "save()"),
    ("expect(() => total()).not.toThrow();", VITEST, "unknown", "() => total()"),
    ("expect(save()).resolves.toBe(78.75);", VITEST, "unknown", "save()"),
    ("expect(save).toHaveBeenCalledWith(78.75);", VITEST, "unknown", "save"),
    ("expect(save).toHaveBeenCalledTimes(1);", VITEST, "unknown", "save"),
    ("expect([value]).toHaveLength(1);", VITEST, "unknown", "[value]"),
    ("expect({ value }).toMatchObject({ value: 78.75 });", VITEST, "unknown", "{ value }"),
    ("expect(value).toMatchSnapshot();", VITEST, "unknown", "value"),
    ("expect.assertions(1);", VITEST, "unknown", "1"),
    ("expect.soft(value).toBe(78.75);", VITEST, "unknown", "value"),
    # chai chains and assert methods the scan does not read.
    ("expect(() => total(-1)).to.throw(RangeError);", CHAI, "raises", "() => total(-1)"),
    ("expect(save()).to.be.rejectedWith(Error);", CHAI, "raises", "save()"),
    ("expect(() => total()).to.not.throw();", CHAI, "unknown", "() => total()"),
    # `.property` is read since #215; these rows keep spellings the scan does not read.
    ("expect({ value }).to.have.keys('value');", CHAI, "unknown", "{ value }"),
    ("expect({ value }).to.be.an('object').that.has.keys('value');", CHAI, "unknown", "{ value }"),
    ("assert.throws(() => total(-1));", CHAI, "raises", "() => total(-1)"),
    ("assert.isRejected(save());", CHAI, "raises", "save()"),
    ("assert.hasAllKeys({ value }, ['value']);", CHAI, "unknown", "{ value }"),
])
def test_an_unread_assertion_is_recorded_with_no_strength(body, header, form, left):
    (recorded_form, strength, recorded_left, text), = _recorded(body, header)
    assert (recorded_form, strength, recorded_left) == (form, None, left)
    assert text == body.rstrip(";").removeprefix("await ")


@pytest.mark.parametrize("body,header", [
    # Lookalikes: not the assertion API, so not an assertion.
    ("{ assert.throws = () => {}; } assert.throws(() => total(-1));", NODE),
    ("const expect = (actual) => ({ toThrow() {} }); expect(() => total(-1)).toThrow();", VITEST),
    ("assert.throws(() => total(-1));", 'import { test } from "node:test";\nimport assert from "./support/assert.js";\n'),
    ("expect(() => total(-1)).toThrow();", 'import { test } from "node:test";\nimport { expect } from "./support/expect.js";\n'),
    # Not an assertion at all.
    ("expect(value);", VITEST),
    ("const matcher = expect.any(Number);", VITEST),
    ("expect.extend({ toBePaid() { return { pass: true, message: () => '' }; } });", VITEST),
    ("assert.okay(value);", NODE),
    # A matcher the scan reads, left out for its arguments, stays out.
    ("expect(value).toBe();", VITEST),
    ("assert.strictEqual(value);", NODE),
    # Each runner's own style only.
    ("expect(value).toBe(78.75);", CHAI),
    ("expect([value]).toHaveLength(1);", CHAI),
    ("expect(value).to.equal(78.75);", JEST_GLOBALS),
    # Inside a nested function, a helper the test may never call.
    ("function check() { expect(() => total(-1)).toThrow(); }", VITEST),
])
def test_what_is_not_an_unread_assertion_is_not_recorded(body, header):
    assert [entry for entry in _recorded(body, header) if entry[1] is None] == []


@pytest.mark.parametrize("body,header,expected", [
    ("expect(save).toHaveBeenCalledWith(expect.any(Number));", VITEST, [("unknown", None)]),
    ("expect(assert.match(String(value), /78/)).toBeUndefined();", VITEST_NODE, [("non_null", 30)]),
])
def test_a_call_inside_another_assertion_is_not_recorded_on_its_own(body, header, expected):
    assert [(form, strength) for form, strength, _left, _text in _recorded(body, header)] == expected


def test_a_read_assertion_keeps_its_strength():
    assert [(form, strength) for form, strength, _left, _text in _recorded("expect(value).toBe(78.75);", VITEST)] == [
        ("compare_eq", 90)]


# --- What is reported -----------------------------------------------------------------

@pytest.mark.parametrize("body,header,strength", [
    ("expect(() => total(-1)).toThrow(RangeError);", VITEST, "UNKNOWN"),
    ("expect(save).toHaveBeenCalledWith(78.75);", VITEST, "UNKNOWN"),
    ("assert.throws(() => total(-1), RangeError);", NODE, "UNKNOWN"),
    ("assert.rejects(save());", NODE, "UNKNOWN"),
    ("expect({ value }).to.have.keys('value');", CHAI, "UNKNOWN"),
    ("assert.isRejected(save());", CHAI, "UNKNOWN"),
])
def test_deleting_an_unread_assertion_is_assert_removed(body, header, strength):
    verdict, findings, messages = _outcome(body, "", header)
    assert verdict == BLOCK, messages
    assert ("ASSERT_REMOVED", "high") in findings, messages
    assert any(f"assertion removed (strength {strength})" in message for message in messages), messages


@pytest.mark.parametrize("before,after,header", [
    # A rewrite is not judged: the predicate is not read.
    ("expect(save).toHaveBeenCalledWith(78.75);", "expect(save).toHaveBeenCalledWith(75);", VITEST),
    ("expect(() => total(-1)).toThrow(RangeError);", "expect(() => total(-1)).toThrow(Error);", VITEST),
    ("assert.throws(() => total(-1), RangeError);", "assert.throws(() => total(-1));", NODE),
    # A respelled call keeps its text-normalized identity.
    ("expect(save).toHaveBeenCalledWith(78.75);", "expect(save)\n    .toHaveBeenCalledWith(78.75);", VITEST),
])
def test_rewriting_an_unread_assertion_is_not_judged(before, after, header):
    verdict, findings, messages = _outcome(before, after, header)
    assert (verdict, findings) == (PASS, ()), messages


def test_a_spy_check_rewritten_into_an_exact_check_is_a_compensated_removal():
    verdict, findings, messages = _outcome("expect(save).toHaveBeenCalledWith(78.75);",
                                           "expect(save.mock.calls[0][0]).toBe(78.75);", VITEST)
    assert (verdict, findings) == (PASS, (("ASSERT_REMOVED", "warn"),)), messages


def test_an_exact_check_rewritten_into_an_unread_one_is_still_removed():
    verdict, findings, messages = _outcome("expect([value]).toEqual([78.75]);", "expect([value]).toHaveLength(1);",
                                           VITEST)
    assert verdict == BLOCK, messages
    assert ("ASSERT_REMOVED", "high") in findings, messages


def test_deleting_a_lookalike_is_still_no_finding():
    header = 'import { test } from "node:test";\nimport assert from "./support/assert.js";\n'
    verdict, findings, messages = _outcome("assert.throws(() => total(-1));", "", header)
    assert (verdict, findings) == (PASS, ()), messages


# --- Coverage -------------------------------------------------------------------------

def test_a_recorded_assertion_stays_a_coverage_notice_that_says_so():
    data = _source("assert.match(String(value), /78/);", NODE).encode()
    gap, = javascript_coverage_gaps(data, parse_javascript(data), PATH, "after")
    assert gap.callee == "assert.match"
    assert "recorded with no strength" in gap.reason
    assert "not represented" in gap.reason


def test_an_unrecorded_candidate_keeps_its_notice():
    data = _source("assert.okay(value);", NODE).encode()
    gap, = javascript_coverage_gaps(data, parse_javascript(data), PATH, "after")
    assert gap.callee == "assert.okay"
    assert gap.reason == "Node assertion candidate is not represented in the assertion scan"
