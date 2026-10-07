"""Issue #215: chai grammar coverage, should-style and property retargeting.

v0.5.0 (#190) read two chai forms, `expect(...)` chains and the `assert`
interface. Should-style (`total.should.equal(78.75)`) was not read at all:
weakening, rewriting or deleting one gave no finding and no diagnostic. A
property assertion (`expect(order).to.have.property("total", 78.75)`,
`assert.propertyVal(order, "total", 78.75)`) was a coverage gap, so dropping
or rewriting its value passed, and respelling `expect(order.total).to.equal(
78.75)` as one blocked as a removal (N1).

Ruling (#196, 2026-10-03; maintainer decision on #215, 2026-10-06):
- should-style is judged in full, mapped onto the lattice as `expect` chains
  are: `value.should.<chain>` is `expect(value).<chain>`, and the should
  object's `equal` and `exist` (with `not`) take the subject first;
- `.property(name[, value])`, its `nested` and `own` forms and
  `assert.property`/`propertyVal`/`deepPropertyVal` retarget the assertion to
  `subject[name]`, with the value as the expectation; `.property(name)` alone
  asserts that the key is there (TYPE_SHAPE, an existing rung).
"""

import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript, property_subject

BLOCK, PASS = "block", "pass"
EXPECT = 'import { expect } from "chai";\n'
ASSERT = 'import { expect, assert } from "chai";\n'
SHOULD = 'import { should } from "chai";\nshould();\n'
PATH = "test/billing.spec.js"


def _spec(line, head=EXPECT):
    return (head + 'import { invoiceTotal, makeOrder } from "../src/billing.js";\n\n'
            'describe("billing", function () {\n  it("computes invoice total", function () {\n'
            '    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n'
            '    const order = makeOrder(items);\n'
            f'    {line}\n  }});\n}});\n')


@functools.lru_cache(maxsize=None)
def _judge(before, after, head=EXPECT):
    changes = [FileChange(PATH, "modified", _spec(before, head).encode(), _spec(after, head).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    return verdict, [(f.rule, f.severity) for f in findings], [f.message for f in findings]


def _recorded(line, head=EXPECT):
    units = parse_javascript(_spec(line, head).encode()).units
    return [(a.form, a.strength, a.left, a.positive, a.right_value)
            for unit in units for a in unit.side.assertions]


def _gaps(line, head=EXPECT):
    source = _spec(line, head).encode()
    return [(gap.callee, gap.reason) for gap in javascript_coverage_gaps(source, parse_javascript(source), PATH,
                                                                        "after")]


WEAKENED = (BLOCK, [("ASSERT_WEAKENED", "high")])
REWRITTEN = (BLOCK, [("EXPECTED_VALUE_CHANGED", "high")])
REMOVED = (BLOCK, [("ASSERT_REMOVED", "high")])
QUIET = (PASS, [])


# --- The issue's rows ------------------------------------------------------------------------

@pytest.mark.parametrize("before, after, head, expected", [
    # Controls, judged before this round.
    ("expect(invoiceTotal(items)).to.equal(78.75);", "expect(invoiceTotal(items)).to.exist;", EXPECT, WEAKENED),
    ("expect(order.total).to.equal(78.75);", "expect(order.total).to.exist;", EXPECT, WEAKENED),
    ("assert.strictEqual(order.total, 78.75);", "assert.isOk(order.total);", ASSERT, WEAKENED),
    ("expect(order.paid).to.be.true;", "expect(order.paid).to.be.ok;", EXPECT, WEAKENED),
    # Should-style.
    ("invoiceTotal(items).should.equal(78.75);", "invoiceTotal(items).should.exist;", SHOULD, WEAKENED),
    ("invoiceTotal(items).should.equal(78.75);", "invoiceTotal(items).should.equal(75);", SHOULD, REWRITTEN),
    ("invoiceTotal(items).should.equal(78.75);", "invoiceTotal(items);", SHOULD, REMOVED),
    ("order.paid.should.be.true;", "order.paid.should.be.ok;", SHOULD, WEAKENED),
    ("invoiceTotal(items).should.equal(78.75);", "invoiceTotal(items).should.exist;",
     'const chai = require("chai");\nchai.should();\n', WEAKENED),
    ("invoiceTotal(items).should.equal(78.75);", "invoiceTotal(items).should.exist;",
     'import "chai/register-should";\n', WEAKENED),
    ("should.equal(invoiceTotal(items), 78.75);", "should.exist(invoiceTotal(items));",
     'const should = require("chai").should();\n', WEAKENED),
    # Property assertions.
    ('expect(order).to.have.property("total", 78.75);', 'expect(order).to.have.property("total");', EXPECT, WEAKENED),
    ('expect(order).to.have.property("total", 78.75);', 'expect(order).to.have.property("total", 75);', EXPECT,
     REWRITTEN),
    ('expect(order).to.have.nested.property("totals.gross", 78.75);',
     'expect(order).to.have.nested.property("totals.gross");', EXPECT, WEAKENED),
    ('expect(order).to.have.own.property("total", 78.75);', 'expect(order).to.have.own.property("total");', EXPECT,
     WEAKENED),
    ('expect(order).to.have.property("total").that.equals(78.75);', 'expect(order).to.have.property("total");',
     EXPECT, WEAKENED),
    ('assert.propertyVal(order, "total", 78.75);', 'assert.property(order, "total");', ASSERT, WEAKENED),
    ('assert.deepPropertyVal(order, "line", { price: 10.0, qty: 3 });', 'assert.property(order, "line");', ASSERT,
     WEAKENED),
    ('assert.propertyVal(order, "total", 78.75);', 'assert.propertyVal(order, "total", 75);', ASSERT, REWRITTEN),
], ids=["C0", "C1", "C2", "C4", "SH1", "SH2", "SH3", "SH4", "SH5", "SH6", "SH7",
        "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"])
def test_the_issues_rows_are_judged(before, after, head, expected):
    verdict, findings, messages = _judge(before, after, head)
    assert (verdict, [(rule, severity) for rule, severity in findings]) == expected, messages


@pytest.mark.parametrize("before, after, head", [
    ('expect(order.total).to.equal(78.75);', 'expect(order).to.have.property("total", 78.75);', EXPECT),
    ('expect(order).to.have.property("total", 78.75);', 'assert.propertyVal(order, "total", 78.75);', ASSERT),
    ('expect(order).to.have.property("total").that.equals(78.75);', 'expect(order.total).to.equal(78.75);', EXPECT),
    ("invoiceTotal(items).should.equal(78.75);", "expect(invoiceTotal(items)).to.equal(78.75);",
     'import { expect, should } from "chai";\nshould();\n'),
    ('order.should.have.property("total", 78.75);', "expect(order.total).to.equal(78.75);",
     'import { expect, should } from "chai";\nshould();\n'),
    ('expect(order).to.have.nested.property("totals.gross", 78.75);', "expect(order.totals.gross).to.equal(78.75);",
     EXPECT),
    ('assert.ownPropertyVal(order, "total", 78.75);', 'assert.propertyVal(order, "total", 78.75);', ASSERT),
    ("new Date(0).getTime().should.equal(0);", "expect(new Date(0).getTime()).to.equal(0);",
     'import { expect, should } from "chai";\nshould();\n'),
], ids=["N1", "N2", "N3", "SN1", "should_property", "nested", "assert_own", "should_new"])
def test_a_respelling_of_one_check_reports_nothing(before, after, head):
    assert _judge(before, after, head)[:2] == QUIET


# --- Property retargeting ----------------------------------------------------------------------

@pytest.mark.parametrize("subject, name, nested, expected", [
    ("order", '"total"', False, "order.total"),
    ("order", "'total'", False, "order.total"),
    ("order", '"unit price"', False, 'order["unit price"]'),
    ("order", '"0"', False, 'order["0"]'),
    ("order", "key", False, "order[key]"),
    ("order", '"totals.gross"', False, 'order["totals.gross"]'),
    ("order", '"totals.gross"', True, "order.totals.gross"),
    ("order", '"lines[0].price"', True, "order.lines[0].price"),
    ("order", "path", True, None),
    ("order", '"a..b"', True, None),
    ("res.body.items[0]", '"total"', False, "res.body.items[0].total"),
    ("makeOrder(items)", '"total"', False, "makeOrder(items).total"),
    ("a || b", '"total"', False, "(a || b).total"),
    ("{ total }", '"total"', False, "({ total }).total"),
])
def test_property_subject(subject, name, nested, expected):
    assert property_subject(subject, name, nested) == expected


@pytest.mark.parametrize("line, head, expected", [
    # Presence is a shape check on the property; a value is its expectation.
    ('expect(order).to.have.property("total");', EXPECT, [("type_shape", 50, "order.total", True, None)]),
    ('expect(order).to.have.property("total", 78.75);', EXPECT, [("compare_eq", 90, "order.total", True, "78.75")]),
    ('expect(order).to.have.deep.property("line", { qty: 3 });', EXPECT,
     [("compare_eq", 100, "order.line", True, None)]),
    ('expect(order).to.have.deep.own.property("line", { qty: 3 });', EXPECT,
     [("compare_eq", 100, "order.line", True, None)]),
    ('expect(order).to.have.own.property("total");', EXPECT, [("type_shape", 50, "order.total", True, None)]),
    ('expect(order).to.have.ownProperty("total");', EXPECT, [("type_shape", 50, "order.total", True, None)]),
    ('expect(order).to.haveOwnProperty("total", 78.75);', EXPECT,
     [("compare_eq", 90, "order.total", True, "78.75")]),
    ('expect(order).to.have.nested.property("totals.gross", 78.75);', EXPECT,
     [("compare_eq", 90, "order.totals.gross", True, "78.75")]),
    ('expect(order).to.have.property("total", 78.75, "a message");', EXPECT,
     [("compare_eq", 90, "order.total", True, "78.75")]),
    # A negated chain negates the assertion on the property.
    ('expect(order).to.not.have.property("total");', EXPECT, [("type_shape", 50, "order.total", False, None)]),
    ('expect(order).to.not.have.property("total", 75);', EXPECT, [("compare_eq", 90, "order.total", False, "75.0")]),
    # The rest of a chain asserts on the property it names.
    ('expect(order).to.have.property("total").that.equals(78.75);', EXPECT,
     [("compare_eq", 90, "order.total", True, "78.75")]),
    ('expect(order).to.have.property("total").that.is.above(70);', EXPECT,
     [("compare_ord", 40, "order.total", True, "70.0")]),
    ('expect(order).to.have.property("totals").with.property("gross", 78.75);', EXPECT,
     [("compare_eq", 90, "order.totals.gross", True, "78.75")]),
    ('expect(order).to.have.property("total").and.not.equal(0);', EXPECT,
     [("compare_eq", 90, "order.total", False, "0.0")]),
    ("expect(order).to.have.property(key, 78.75);", EXPECT, [("compare_eq", 90, "order[key]", True, "78.75")]),
    # The assert interface.
    ('assert.property(order, "total");', ASSERT, [("type_shape", 50, "order.total", True, None)]),
    ('assert.ownProperty(order, "total");', ASSERT, [("type_shape", 50, "order.total", True, None)]),
    ('assert.nestedProperty(order, "totals.gross");', ASSERT, [("type_shape", 50, "order.totals.gross", True, None)]),
    ('assert.propertyVal(order, "total", 78.75);', ASSERT, [("compare_eq", 90, "order.total", True, "78.75")]),
    ('assert.ownPropertyVal(order, "total", 78.75);', ASSERT, [("compare_eq", 90, "order.total", True, "78.75")]),
    ('assert.deepPropertyVal(order, "line", { qty: 3 });', ASSERT, [("compare_eq", 100, "order.line", True, None)]),
    ('assert.deepOwnPropertyVal(order, "line", { qty: 3 });', ASSERT,
     [("compare_eq", 100, "order.line", True, None)]),
    ('assert.nestedPropertyVal(order, "totals.gross", 78.75);', ASSERT,
     [("compare_eq", 90, "order.totals.gross", True, "78.75")]),
    ('assert.deepNestedPropertyVal(order, "totals.line", { qty: 3 });', ASSERT,
     [("compare_eq", 100, "order.totals.line", True, None)]),
    ('assert.propertyVal(order, "total", 78.75, "a message");', ASSERT,
     [("compare_eq", 90, "order.total", True, "78.75")]),
])
def test_a_property_assertion_is_on_the_property(line, head, expected):
    assert _recorded(line, head) == expected


@pytest.mark.parametrize("line, head", [
    # A path that is not a literal cannot be followed.
    ("expect(order).to.have.nested.property(path, 78.75);", EXPECT),
    ("assert.nestedProperty(order, path);", ASSERT),
    # A negated property with a chain after it, and the negated assert methods.
    ('expect(order).to.not.have.property("total").that.equals(78.75);', EXPECT),
    ('assert.notProperty(order, "total");', ASSERT),
    ('assert.notPropertyVal(order, "total", 78.75);', ASSERT),
    ('assert.notDeepPropertyVal(order, "line", { qty: 3 });', ASSERT),
    # Too few arguments.
    ("assert.property(order);", ASSERT),
    ('assert.propertyVal(order, "total");', ASSERT),
])
def test_a_property_assertion_that_cannot_be_followed_is_recorded_with_no_strength(line, head):
    assert [(form, strength) for form, strength, *_rest in _recorded(line, head)] == [("unknown", None)]
    assert len(_gaps(line, head)) == 1


def test_a_polarity_flip_on_a_property_is_reported():
    verdict, findings, messages = _judge('expect(order).to.have.property("total");',
                                         'expect(order).to.not.have.property("total");')
    assert (verdict, findings) == WEAKENED
    assert "polarity inverted" in messages[0]


def test_a_dropped_value_names_both_rungs():
    _verdict, _findings, messages = _judge('expect(order).to.have.property("total", 78.75);',
                                           'expect(order).to.have.property("total");')
    assert messages[0].endswith("assertion strength EXACT_VALUE(90) -> TYPE_SHAPE(50)")


def test_own_and_inherited_presence_read_alike():
    """Reading: `own` excludes inherited keys, but both read as presence on the property."""
    assert _judge('expect(order).to.have.own.property("total");', 'expect(order).to.have.property("total");')[:2] \
        == QUIET


@pytest.mark.parametrize("before, after, expected", [
    # Reading: presence sits on TYPE_SHAPE, above NON_NULL, although neither implies the other.
    ("expect(order.total).to.exist;", 'expect(order).to.have.property("total");', QUIET),
    ('expect(order).to.have.property("total");', "expect(order.total).to.exist;", WEAKENED),
])
def test_presence_and_existence_compare_by_their_rungs(before, after, expected):
    assert _judge(before, after)[:2] == expected


def test_a_deleted_property_assertion_is_removed_at_its_rung():
    _verdict, findings, messages = _judge('expect(order).to.have.property("total");', "makeOrder(items);")
    assert findings == [("ASSERT_REMOVED", "high")]
    assert messages[0].endswith("assertion removed (strength TYPE_SHAPE)")


# --- Should-style --------------------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("total().should.equal(78.75);", [("compare_eq", 90, "total()", True, "78.75")]),
    ("total().should.not.equal(75);", [("compare_eq", 90, "total()", False, "75.0")]),
    ("total().should.be.above(70);", [("compare_ord", 40, "total()", True, "70.0")]),
    # `.exist` asserts the negation of is_nullish (#198), so it records positive=False.
    ("total().should.exist;", [("non_null", 30, "total()", False, None)]),
    ("order.paid.should.be.true;", [("compare_eq", 90, "order.paid", True, "True")]),
    ("order.paid.should.be.ok;", [("truthy", 20, "order.paid", True, None)]),
    ("order.lines.should.have.lengthOf(2);", [("type_shape", 50, "order.lines", True, None)]),
    ("order.should.eql({ total: 78.75 });", [("compare_eq", 100, "order", True, None)]),
    ('order.should.have.property("total", 78.75);', [("compare_eq", 90, "order.total", True, "78.75")]),
    ('order.should.have.property("total").that.equals(78.75);', [("compare_eq", 90, "order.total", True, "78.75")]),
    ("order?.total.should.equal(78.75);", [("compare_eq", 90, "order?.total", True, "78.75")]),
    ("res.body.items[0].should.equal(78.75);", [("compare_eq", 90, "res.body.items[0]", True, "78.75")]),
    ("(5).should.equal(5);", [("compare_eq", 90, "(5)", True, "5.0")]),
    ("[1, 2].should.have.lengthOf(2);", [("type_shape", 50, "[1, 2]", True, None)]),
    ("'abc'.should.match(/b/);", [("pattern", 60, "'abc'", True, None)]),
    # `new` binds before the member access: the subject is the new instance.
    ("new Date(0).getTime().should.equal(0);", [("compare_eq", 90, "new Date(0).getTime()", True, "0.0")]),
])
def test_a_should_chain_reads_as_its_expect_chain(line, expected):
    assert _recorded(line, SHOULD) == expected
    assert _gaps(line, SHOULD) == []


@pytest.mark.parametrize("line, head, expected", [
    ("should.equal(total(), 78.75);", 'const should = require("chai").should();\n',
     [("compare_eq", 90, "total()", True, "78.75")]),
    ("should.not.equal(total(), 75);", 'const should = require("chai").should();\n',
     [("compare_eq", 90, "total()", False, "75.0")]),
    ("should.exist(total());", 'import chai from "chai";\nconst should = chai.should();\n',
     [("non_null", 30, "total()", False, None)]),
    ("should.not.exist(order.error);", 'import chai from "chai";\nconst should = chai.Should();\n',
     [("non_null", 30, "order.error", True, None)]),
])
def test_the_should_objects_methods_take_the_subject_first(line, head, expected):
    assert _recorded(line, head) == expected


@pytest.mark.parametrize("line, expected", [
    ("should.equal(total(), 78.75);", [("compare_eq", 90, "total()", True, "78.75")]),
    ("should.not.exist(order.error);", [("non_null", 30, "order.error", True, None)]),
])
def test_an_undeclared_should_is_the_global_chai_register_should_sets(line, expected):
    """`chai/register-should` sets the global `should` to the object `chai.should()` returns."""
    assert _recorded(line, "") == expected


@pytest.mark.parametrize("line, head", [
    ("should.exist(total());", "const should = require('should');\n"),
    ("should(total()).be.ok;", ""),
    ("const should = { equal() {} }; should.equal(total(), 78.75);", ""),
])
def test_a_should_that_is_not_chais_is_not_read(line, head):
    assert _recorded(line, head) == []


@pytest.mark.parametrize("line, callee", [
    ("order.should.have.keys('total');", "order.should.have.keys"),
    ("total().should.be.a('number');", "total().should.be.a"),
    ("fetchTotal().should.eventually.equal(78.75);", "fetchTotal().should.eventually.equal"),
    # A chain that continues after its terminal; the gap names it up to its first call.
    ("total().should.equal(78.75).and.be.above(0);", "total().should.equal"),
])
def test_a_should_chain_the_reader_declines_is_recorded_with_no_strength(line, callee):
    (form, strength, _left, _positive, _right), = _recorded(line, SHOULD)
    assert (form, strength) == ("unknown", None)
    (gap_callee, reason), = _gaps(line, SHOULD)
    assert gap_callee == callee
    assert reason.startswith("chai assertion candidate is recorded with no strength")


def test_the_coverage_notice_names_a_new_instance_as_written():
    assert _gaps("new Date(0).should.be.an.instanceof(Date);", SHOULD) == [(
        "new Date(0).should.be.an.instanceof",
        "chai assertion candidate is recorded with no strength: its predicate is not represented in the "
        "assertion scan, so a rewrite is not judged")]


def test_deleting_an_unread_should_chain_is_assert_removed():
    verdict, findings, messages = _judge("order.should.have.keys('total');", "makeOrder(items);", SHOULD)
    assert (verdict, findings) == REMOVED
    assert messages[0].endswith("assertion removed (strength UNKNOWN)")


def test_should_throw_is_a_raises_assertion_with_no_strength():
    head = 'const should = require("chai").should();\n'
    assert _recorded("should.Throw(() => total(-1));", head) == [("raises", None, "() => total(-1)", True, None)]
    (callee, reason), = _gaps("should.Throw(() => total(-1));", head)
    assert callee == "should.Throw"
    assert reason.startswith("chai assertion candidate is recorded with no strength")


@pytest.mark.parametrize("line", [
    "chai.should();",
    'require("chai").should();',
    "const flag = options.should;",
    "options.should = true;",
    "if (options.should) { makeOrder(items); }",
    "options.should(order);",
    "should();",
])
def test_what_asserts_nothing_is_not_recorded(line):
    head = 'import chai from "chai";\nimport { should } from "chai";\nconst options = {};\n'
    assert _recorded(line, head) == []
    assert _gaps(line, head) == []


def test_a_should_chain_outside_a_test_is_a_coverage_gap():
    source = (SHOULD + "function check(order) {\n  order.should.have.keys('total');\n}\n").encode()
    gaps = javascript_coverage_gaps(source, parse_javascript(source), PATH, "after")
    assert [(gap.callee, gap.reason) for gap in gaps] == [
        ("order.should.have.keys", "chai assertion candidate is not represented in the assertion scan")]


def test_a_should_chain_is_read_without_a_visible_setup():
    """`chai.should()` may run in a setup file the runner loads, so the chain is read wherever a test spells it."""
    assert _recorded("total().should.equal(78.75);", "") == [("compare_eq", 90, "total()", True, "78.75")]


# --- Flags ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    # As in chai, the flags stay set for the rest of the chain.
    ('expect(order).to.have.nested.property("a.b").that.has.property("c.d", 1);',
     [("compare_eq", 90, "order.a.b.c.d", True, "1.0")]),
    ('expect(order).to.have.deep.property("line").that.equals({ qty: 3 });',
     [("compare_eq", 100, "order.line", True, None)]),
    ('expect(order).to.have.property("items").that.includes(3);', [("membership", 60, "order.items", True, None)]),
])
def test_the_flags_stay_set_after_a_property(line, expected):
    assert _recorded(line) == expected


@pytest.mark.parametrize("line", [
    "expect(order).to.have.own.include({ total: 1 });",
    'expect(order).to.have.nested.include({ "a.b": 1 });',
    "expect(order).to.deep.own.include({ total: 1 });",
    'expect(order).to.have.own.property("line").that.includes({ qty: 3 });',
])
def test_include_with_own_or_nested_stays_unread(line):
    """`include` reads both flags, which this scan does not model."""
    assert [(form, strength) for form, strength, *_rest in _recorded(line)] == [("unknown", None)]
