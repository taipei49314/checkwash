"""chai assertion styles on the existing strength lattice (issue #180).

Forms, rungs and values below are written from chai's documented semantics,
not read from the frontend tables, so dropping a spelling fails here. The
independent mutation supplement is tests/data/javascript_chai_mutations.json;
it runs in-process here; wiring it into the CLI qualification is left
to the maintainer.
"""

import datetime
from pathlib import Path
import runpy

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript

_CHAI = 'import { assert, expect } from "chai";'
_PATH = "test/billing.spec.js"


def _source(body, imports=_CHAI):
    return "\n".join([
        imports,
        'describe("billing", function () {',
        '  it("total", function () {',
        f"    {body}",
        "  });",
        "});",
        "",
    ])


def _assertions(source):
    return [assertion for unit in parse_javascript(source.encode()).units
            for assertion in unit.side.assertions]


def _gaps(source, path=_PATH):
    data = source.encode()
    return javascript_coverage_gaps(data, parse_javascript(data), path, "after")


def _outcome(before, after, path=_PATH):
    _ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 1),
    )
    return verdict, [(finding.rule, finding.severity) for finding in findings]


@pytest.mark.parametrize("body,subject,form,strength,positive,value", [
    ("expect(total()).to.equal(78.75);", "total()", "compare_eq", 90, True, "78.75"),
    ("expect(total()).equals(78.75);", "total()", "compare_eq", 90, True, "78.75"),
    ("expect(total(), 'total').to.eq(78.75, 'message');", "total()", "compare_eq", 90, True, "78.75"),
    ("expect(total()).not.to.equal(80);", "total()", "compare_eq", 90, False, "80.0"),
    ("expect(lines()).to.deep.equal([1, 2]);", "lines()", "compare_eq", 100, True, None),
    ("expect(total()).to.eql(78.75);", "total()", "compare_eq", 100, True, "78.75"),
    ("expect(paid()).to.be.true;", "paid()", "compare_eq", 90, True, "True"),
    ("expect(paid()).to.be.false;", "paid()", "compare_eq", 90, True, "False"),
    ("expect(failure()).to.be.null;", "failure()", "compare_eq", 90, True, "None"),
    ("expect(failure()).to.be.undefined;", "failure()", "compare_eq", 90, True, None),
    ("expect(failure()).to.exist;", "failure()", "non_null", 30, True, None),
    ("expect(failure()).to.not.exist;", "failure()", "non_null", 30, False, None),
    ("expect(paid()).to.be.ok;", "paid()", "truthy", 20, True, None),
    ("expect(paid()).to.be.ok();", "paid()", "truthy", 20, True, None),
    ("expect(total()).to.be.closeTo(78.75, 0.01);", "total()", "approx", 70, True, "78.75"),
    ("expect(total()).to.be.approximately(78.75, 0.01);", "total()", "approx", 70, True, "78.75"),
    ("expect(lines()).to.include(2);", "lines()", "membership", 60, True, None),
    ("expect(lines()).to.contain(2);", "lines()", "membership", 60, True, None),
    ("expect(name()).to.match(/total/);", "name()", "pattern", 60, True, None),
    ("expect(total()).to.be.above(70);", "total()", "compare_ord", 40, True, None),
    ("expect(total()).to.be.at.least(70);", "total()", "compare_ord", 40, True, None),
    ("expect(total()).to.be.below(80);", "total()", "compare_ord", 40, True, None),
    ("expect(total()).to.be.at.most(80);", "total()", "compare_ord", 40, True, None),
    ("expect(total()).to.be.within(70, 80);", "total()", "compare_ord", 40, True, None),
    ("expect(lines()).to.have.lengthOf(2);", "lines()", "type_shape", 50, True, None),
    ("expect(total())\n      .to.equal(78.75);", "total()", "compare_eq", 90, True, "78.75"),
    ("assert(paid());", "paid()", "truthy", 20, True, None),
    ("assert.isOk(paid(), 'message');", "paid()", "truthy", 20, True, None),
    ("assert.equal(total(), 78.75);", "total()", "compare_eq", 90, True, None),
    ("assert.strictEqual(total(), 78.75);", "total()", "compare_eq", 90, True, "78.75"),
    ("assert.deepEqual(total(), 78.75);", "total()", "compare_eq", 100, True, "78.75"),
    ("assert.isTrue(paid());", "paid()", "compare_eq", 90, True, "True"),
    ("assert.isNull(failure());", "failure()", "compare_eq", 90, True, "None"),
    ("assert.exists(failure());", "failure()", "non_null", 30, True, None),
    ("assert.isDefined(failure());", "failure()", "non_null", 30, True, None),
    ("assert.closeTo(total(), 78.75, 0.01);", "total()", "approx", 70, True, "78.75"),
    ("assert.include(lines(), 2);", "lines()", "membership", 60, True, None),
    ("assert.match(name(), /total/);", "name()", "pattern", 60, True, None),
    ("assert.isAtLeast(total(), 70);", "total()", "compare_ord", 40, True, None),
    ("assert.lengthOf(lines(), 2);", "lines()", "type_shape", 50, True, None),
])
def test_chai_spellings_reach_the_existing_lattice(body, subject, form, strength, positive, value):
    source = _source(body)
    assertion, = _assertions(source)
    assert (assertion.left, assertion.form, assertion.strength, assertion.positive,
            assertion.right_value) == (subject, form, strength, positive, value)
    assert assertion.text == body.rstrip(";")
    assert _gaps(source) == []


def test_property_terminal_text_ends_at_its_word():
    # Semicolon-free style: a trailing comment and the next line's comment
    # belong to no assertion, so editing them cannot change this one's text.
    source = _source("expect(paid()).to.be.true // settled\n"
                     "    // totals next\n"
                     "    expect(total()).to.equal(78.75)")
    first, second = _assertions(source)
    assert first.text == "expect(paid()).to.be.true"
    assert second.text == "expect(total()).to.equal(78.75)"


def test_editing_the_comment_after_a_kept_property_does_not_excuse_a_removal():
    # The kept assertion is not newly written, so SAME_UNIT_REWRITE must not
    # hold the other assertion's removal at warn.
    before = _source("expect(paid()).to.be.true\n"
                     "    // settled first\n"
                     "    expect(total()).to.equal(78.75)")
    after = _source("expect(paid()).to.be.true\n"
                    "    // settled first, the total is checked elsewhere")
    assert _outcome(before, after) == ("block", [("ASSERT_REMOVED", "high")])


def test_repeated_not_keeps_chai_negation():
    # chai's `not` sets the negate flag; a second `not` does not clear it.
    assertion, = _assertions(_source("expect(total()).not.to.not.equal(80);"))
    assert assertion.positive is False


@pytest.mark.parametrize("body", [
    "expect(total()).to.be.closeTo(78.75, 0.01);",
    "expect(total()).to.be.approximately(78.75, 1e-2, 'message');",
    "assert.closeTo(total(), 78.75, 0.010);",
])
def test_close_to_records_its_absolute_delta(body):
    assertion, = _assertions(_source(body))
    assert (assertion.epsilon, assertion.epsilon_kind) == ("0.01", "delta")


@pytest.mark.parametrize("body", [
    "expect(total()).not.to.be.closeTo(78.75, 0.01);",
    "expect(total()).to.be.closeTo(78.75, tolerance);",
    "expect(total()).to.be.closeTo(78.75, Infinity);",
])
def test_unknown_or_negated_delta_claims_no_ordering(body):
    assertion, = _assertions(_source(body))
    assert assertion.form == "approx"
    assert assertion.epsilon is None


@pytest.mark.parametrize("imports,receiver", [
    ('import { expect } from "chai";', "expect"),
    ('import { expect as check } from "chai";', "check"),
    ('import * as chai from "chai";', "chai.expect"),
    ('import chai from "chai";', "chai.expect"),
    ('const { expect } = require("chai");', "expect"),
    ('const expect = require("chai").expect;', "expect"),
    ('const chai = require("chai");\nconst { expect } = chai;', "expect"),
    ('import { expect } from "vitest";', "expect"),
    ("", "expect"),
])
def test_chai_expect_bindings_report_the_issue_weakening(imports, receiver):
    before = _source(f"{receiver}(total()).to.equal(78.75);", imports)
    after = _source(f"{receiver}(total()).to.exist;", imports)
    assert _outcome(before, after) == ("block", [("ASSERT_WEAKENED", "high")])


@pytest.mark.parametrize("imports,receiver", [
    ('import { assert } from "chai";', "assert"),
    ('import { assert as check } from "chai";', "check"),
    ('import * as chai from "chai";', "chai.assert"),
    ('const { assert } = require("chai");', "assert"),
    ('const assert = require("chai").assert;', "assert"),
    ('import { assert } from "vitest";', "assert"),
])
def test_chai_assert_bindings_report_a_truthiness_weakening(imports, receiver):
    before = _source(f"{receiver}.strictEqual(total(), 78.75);", imports)
    after = _source(f"{receiver}.isOk(total());", imports)
    assert _outcome(before, after) == ("block", [("ASSERT_WEAKENED", "high")])


@pytest.mark.parametrize("imports,body", [
    ('import { expect } from "./support/expect.js";', "expect(total()).to.equal(78.75);"),
    ('import { assert } from "./support/assert.js";', "assert.strictEqual(total(), 78.75);"),
    (_CHAI, "const expect = standin; expect(total()).to.equal(78.75);"),
    (_CHAI, "const assert = standin; assert.strictEqual(total(), 78.75);"),
])
def test_lookalikes_and_shadows_do_not_acquire_chai_strength(imports, body):
    source = _source(body, imports)
    assert _assertions(source) == []
    gap, = _gaps(source)
    assert "unresolved" in gap.reason


@pytest.mark.parametrize("body,callee", [
    ("expect(total()).to.equal(78.75).and.not.equal(80);", "expect(...).to.equal"),
    ("expect(total()).to.eventually.equal(78.75);", "expect(...).to.eventually.equal"),
    ("expect(lines()).to.be.an('array');", "expect(...).to.be.an"),
    ("expect(lines()).to.have.length.above(1);", "expect(...).to.have.length.above"),
    ("expect(order()).to.have.own.property('total');", "expect(...).to.have.own.property"),
    ("expect(total()).to.be.closeTo(78.75);", "expect(...).to.be.closeTo"),
    ("assert.isFunction(total);", "assert.isFunction"),
    ("assert.notStrictEqual(total(), 80);", "assert.notStrictEqual"),
])
def test_unsupported_chai_spellings_remain_coverage_gaps(body, callee):
    source = _source(body)
    assert _assertions(source) == []
    gap, = _gaps(source)
    assert gap.callee == callee
    assert "not represented" in gap.reason


def test_chai_expect_has_no_jest_matchers():
    source = _source("expect(total()).toBe(78.75);")
    assert _assertions(source) == []
    gap, = _gaps(source)
    assert gap.callee == "expect(...).toBe"


def test_unimported_assert_keeps_the_node_default():
    source = _source("assert.isTrue(paid());", imports="")
    assert _assertions(source) == []
    gap, = _gaps(source)
    assert gap.callee == "assert.isTrue"
    assert gap.reason.startswith("Node ")


@pytest.mark.parametrize("body,callees", [
    ("vitest.assert.notStrictEqual(total(), 80);", ["vitest.assert.notStrictEqual"]),
    ("vitest.assert.strictEqual(total(), 78.75);", []),
    ("vitest.vi.fn();", []),
])
def test_vitest_namespace_assert_member_is_a_chai_candidate(body, callees):
    # A Vitest namespace exposes chai's assert; its other members are not
    # assertion candidates. A represented call leaves no gap.
    gaps = _gaps(_source(body, 'import * as vitest from "vitest";'))
    assert [(gap.callee, gap.reason.split()[0]) for gap in gaps] == [(callee, "chai") for callee in callees]


def test_should_style_is_outside_the_scan():
    # Recorded boundary: should-style needs receiver-expression and prototype
    # registration modelling that this bounded scan does not have.
    source = _source("total().should.equal(78.75);", 'import { should } from "chai";\nshould();')
    assert _assertions(source) == []
    assert _gaps(source) == []


_ISSUE_180 = '''// billing.test.js: mocha + chai, "type": "module"
import { expect } from "chai";
import { invoiceTotal } from "./src/billing.js";

describe("billing", function () {
  it("computes invoice total", function () {
    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];
    expect(invoiceTotal(items)).to.equal(78.75);
  });
});
'''


def test_issue_180_reproduction_blocks_and_leaves_no_coverage_gap():
    after = _ISSUE_180.replace(".to.equal(78.75);", ".to.exist;")
    assert _outcome(_ISSUE_180, after, "billing.test.js") == ("block", [("ASSERT_WEAKENED", "high")])
    assert _gaps(_ISSUE_180, "billing.test.js") == []
    assert _gaps(after, "billing.test.js") == []


_CONTRACT_TOOLS = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/assertion_contract.py"))
_INVENTORY = _CONTRACT_TOOLS["foundation_mutation_cases"](_CONTRACT_TOOLS["CHAI_CONTRACT"])


@pytest.mark.parametrize("case", _INVENTORY, ids=lambda case: case["id"])
def test_independent_chai_mutations(case):
    _CONTRACT_TOOLS["check_mutation_case"](case)


def test_chai_inventory_covers_every_outcome_kind():
    assert {case["kind"] for case in _INVENTORY} == {
        "weakening", "removal", "expected_rewrite", "tolerance_weakened", "preserving", "strengthening",
    }
