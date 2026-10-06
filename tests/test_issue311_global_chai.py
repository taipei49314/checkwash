"""Issue #311: an undeclared `chai` is chai's module.

karma-chai loads chai's browser build, which defines `window.chai`, and its
adapter sets the `should`, `expect` and `assert` globals from it; chai's own
suite sets `global.chai` in its bootstrap and binds `var expect = chai.expect`
in each `describe`. The JS reader took an undeclared `expect` for chai's
(C2) but not an undeclared `chai`, so every spelling through it (K1-K5) was
unread: `chai.expect(x).to.equal(y)` -> `.to.exist` passed, K5 without even
the coverage banner. A `chai` the file declares, imports or requires keeps
its own binding, as #215 reads an undeclared `should`.
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

PATH = "test/billing.spec.js"
BLOCK, PASS = "block", "pass"


def _spec(line, setup=""):
    return ('const { invoiceTotal } = require("../src/billing.js");\n\n'
            'describe("billing", function () {\n'
            f'  {setup}\n'
            '  it("computes invoice total", function () {\n'
            '    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n'
            f'    {line}\n  }});\n}});\n')


@functools.lru_cache(maxsize=None)
def _judge(before, after, setup=""):
    changes = [FileChange(PATH, "modified", _spec(before, setup).encode(), _spec(after, setup).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    return verdict, [(f.rule, f.severity) for f in findings]


def _recorded(line, setup=""):
    units = parse_javascript(_spec(line, setup).encode()).units
    return [(a.form, a.strength, a.left) for unit in units for a in unit.side.assertions]


def _gaps(line, setup=""):
    source = _spec(line, setup).encode()
    return [gap.callee for gap in javascript_coverage_gaps(source, parse_javascript(source), PATH, "after")]


EQUAL = "expect(invoiceTotal(items)).to.equal(78.75);"
EXIST = "expect(invoiceTotal(items)).to.exist;"
WEAKENED = (BLOCK, [("ASSERT_WEAKENED", "high")])


@pytest.mark.parametrize("before, after, setup, expected", [
    (EQUAL, EXIST, "var expect = chai.expect;", WEAKENED),
    (EQUAL, "expect(invoiceTotal(items)).to.equal(75);", "var expect = chai.expect;",
     (BLOCK, [("EXPECTED_VALUE_CHANGED", "high")])),
    (EQUAL, "invoiceTotal(items);", "var expect = chai.expect;", (BLOCK, [("ASSERT_REMOVED", "high")])),
    ("assert.strictEqual(invoiceTotal(items), 78.75);", "assert.isOk(invoiceTotal(items));",
     "var assert = chai.assert;", WEAKENED),
    ("chai.expect(invoiceTotal(items)).to.equal(78.75);", "chai.expect(invoiceTotal(items)).to.exist;", "", WEAKENED),
    ("chai.assert.strictEqual(invoiceTotal(items), 78.75);", "chai.assert.isOk(invoiceTotal(items));", "", WEAKENED),
    # The controls the issue names: a required chai, and an undeclared expect.
    (EQUAL, EXIST, 'var chai = require("chai"); var expect = chai.expect;', WEAKENED),
    (EQUAL, EXIST, "", WEAKENED),
], ids=["K1", "K2", "K3", "K4", "K5", "K5_assert", "C1", "C2"])
def test_the_issues_rows_are_judged(before, after, setup, expected):
    assert _judge(before, after, setup) == expected


@pytest.mark.parametrize("setup", [
    "var chai = { expect: function () {} }; var expect = chai.expect;",   # a chai the file declares
    'const chai = require("./helpers/chai"); var expect = chai.expect;',  # another module's chai
    "function setup(chai) { return chai.expect; } var expect = setup(x);",  # not the global
])
def test_a_chai_the_file_binds_is_not_chais_module(setup):
    assert _judge(EQUAL, EXIST, setup) == (PASS, [])


def test_a_parameter_named_chai_shadows_the_global():
    line = "(function (chai) { chai.expect(invoiceTotal(items)).to.equal(78.75); })(other);"
    assert _recorded(line) == []


def test_the_global_reads_as_an_imported_chai_does():
    for setup in ("var expect = chai.expect;", 'var chai = require("chai"); var expect = chai.expect;'):
        assert _recorded(EQUAL, setup) == [("compare_eq", 90, "invoiceTotal(items)")], setup
    assert _recorded("chai.expect(invoiceTotal(items)).to.equal(78.75);") == [
        ("compare_eq", 90, "invoiceTotal(items)")]


def test_the_should_object_comes_from_the_global_too():
    # chai's own suite: `var should = chai.Should();` (#215 reads its methods).
    for setup in ("var should = chai.Should();", "var should = chai.should();"):
        verdict, findings = _judge("should.equal(invoiceTotal(items), 78.75);", "should.exist(invoiceTotal(items));",
                                   setup)
        assert (verdict, findings) == WEAKENED, setup


def test_a_member_chai_does_not_export_is_no_candidate():
    # As for an imported chai: only expect and assert assert.
    assert _gaps("chai.use(plugin);") == []
    assert _gaps("chai.config.truncateThreshold = 0;") == []


def test_an_unread_assertion_through_the_global_is_a_coverage_notice():
    # K5 had no banner at all; an unread chai word through the global now has one.
    assert _gaps("chai.expect(order()).to.have.keys('total');") == ["chai.expect(...).to.have.keys"]


def test_window_chai_is_not_read():
    # karma's `window.chai` is the same object, but `window` is no binding the
    # reader follows: a residual (THREATMODEL row 111).
    assert _recorded("window.chai.expect(invoiceTotal(items)).to.equal(78.75);") == []
