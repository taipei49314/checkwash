# Assertion coverage and regression prevention

Issue [#164](https://github.com/taipei49314/checkwash/issues/164) exposed a
frontend omission: Node assertions were absent from the IR, so downstream
detectors could not see them weaken. A green detector suite cannot establish
coverage of syntax it never included. These checks are in the current source
tree; they do not update an already-published wheel, zipapp or Action pin.

## Review the support inventory independently

[`tests/data/javascript_assertion_support.json`](../tests/data/javascript_assertion_support.json)
records concrete spellings, documented API sources, support status and literal
expected IR forms, strengths and subjects. Its expectations are not generated
from the frontend's matcher table or strength constants. Unsupported syntax,
methods and lookalikes are recorded alongside supported APIs. An unsupported
API whose call the frontend records with no strength (see [Assertions
checkwash does not read](#assertions-checkwash-does-not-read)) declares that
recording; its predicate is still not read, and only a supported entry states a
strength.

The inventory has 136 API/context cases and 248 concrete changes:
weakening, removal, preserving edits and strengthening controls. Every supported
entry has both a removal case and a preserving case. The suite checks the IR,
finding rule, severity and verdict. Tests deliberately disable each assertion
family to establish that an omitted family makes the contract fail.

When extending a frontend, review the upstream API and update this inventory
before copying implementation behavior into expectations. Add both a real loss
and a preserving control; retain unsupported entries until their expectations
can be deliberately changed. This finite inventory is not proof of support for
all JavaScript syntax or future upstream APIs.

### Call boundaries and scalar expectations

The separate
[`javascript_foundation_mutations.json`](../tests/data/javascript_foundation_mutations.json)
adds 35 independently authored changes without replacing the original 136 API
cases or 248 mutations. It specifies exact scalar expectation rewrites for
Jest/Vitest and Node assertions, positive `toBeCloseTo` precision decreases,
and callback boundaries. An assertion after a test callback cannot replace or
strengthen an assertion inside that callback. A changed top-level assertion
outside recognized test units remains unrepresented and is reported by coverage
diagnostics; the supplement does not claim to analyze that top-level execution.

Nested test callbacks own their own assertions. Declared or assigned helper
functions and their default parameter expressions do not donate assertions to
the surrounding test. Direct inline callback arguments to other calls retain
the existing lexical coverage, including iterator callbacks, whatever the
call's receiver: `cases.forEach(cb)`, `[[1, 78.75]].forEach(cb)`,
`Object.entries(cases).forEach(cb)`, `(cases).forEach(cb)` and
`cases?.forEach(cb)` alike (#294); this does not prove that an arbitrary
callee executes its callback. A call result called directly (`f()(cb)`) and an
optional call (`fn?.(cb)`) are not member calls, and their callbacks stay
nested functions. Vitest's optional second
`expect(actual, message)` argument is diagnostic text, not the asserted subject.

Preserving controls cover assertion messages, multiline formatting, equivalent
numeric and string spellings, truthiness strengthened to an exact check, and
explicit versus omitted default precision. Converting a legacy Node equality
check to strict equality and removing parentheses around a scalar are also
preserving controls: the first is a strengthening from `==` to `===`, and the
second states the same literal. Each blocking case requires exactly
its stated rule, severity and verdict; preserving cases require no findings.
Ten of these controls were added during v0.4.2 release review: equivalent scalar
spellings cannot invent an assertion substitution or hide subject wrapping and
concrete input changes. Known scalar equality is shared by those consumers;
unknown and Python expectations retain their prior handling. The source tests
are in [`tests/test_js_foundation.py`](../tests/test_js_foundation.py) and
[`tests/test_js_scalar_consumers.py`](../tests/test_js_scalar_consumers.py).

This scope reads complete balanced calls and direct scalar expected arguments:
finite Number literals, quoted strings, booleans and `null`, through redundant
parentheses and TypeScript's `as`, `satisfies` and non-null `!`, which
evaluate to the literal they wrap: `toBe((75))` and `toBe(75 as number)` state
75 ([#198](https://github.com/taipei49314/checkwash/issues/198) T4, T5). It
does not infer expected values from objects, arrays, BigInt, non-finite
numbers, variables or arbitrary expressions; see
[Operand evidence](#operand-evidence) for what an operand that is not a
literal still records. Every Node equality records its scalar: `strictEqual`
and `deepStrictEqual`, including their `t.assert` forms, `equal` and
`deepEqual` in strict mode (imported from `node:assert/strict` or
`assert/strict`, or reached through `assert.strict`, where they are the strict
comparisons), and since the evidence half of #198 the legacy coercive `equal`
and `deepEqual` too: `equal`'s `eq_loose` key carries the coercion, so a
different scalar is still a different expected value (#196 190.2). `toBeCloseTo` precision
evidence covers positive calls with an explicit integer precision from -308
through 307 or the default of two digits;
negated precision is not assigned the same weakening direction. These additions
do not implement general JS/TS parsing, arbitrary helper execution, suite/table
collection, async completion, or production repair evidence.

```bash
python -m pytest tests/test_assertion_contract.py tests/test_js_coverage.py tests/test_js_chai.py
python tools/qualify_assertions.py --distribution source --output receipts/source.json
```

### Hand-rolled tolerances

Issue [#179](https://github.com/taipei49314/checkwash/issues/179) showed that
`assert.ok(Math.abs(total - 78.75) < 0.01)` widened to `< 1e12` reached no
detector, because the whole comparison was an opaque truthy subject. One
predicate shape is now read inside an oracle: a single top-level `<`, `<=`,
`>` or `>=` with an unshadowed `Math.abs(...)` call on its smaller side.
Redundant parentheses around the comparison or either operand do not change
it. It applies to Node's `assert`, `assert.ok` and `t.assert.ok`, to
`assert.strictEqual(..., true)`, to `expect(...).toBeTruthy()` and to
`expect(...).toBe(true)`, `toEqual(true)` and `toStrictEqual(true)`. The
positive ordering matchers read the same shape from their two operands, as in
`expect(Math.abs(d)).toBeLessThan(eps)` or
`expect(eps).toBeGreaterThan(Math.abs(d))`.

What the magnitude measures is the assertion's subject, and a Number literal
centre is its expected value
([#225](https://github.com/taipei49314/checkwash/issues/225), #196 189.2):
`Math.abs(total - 78.75) < 0.01` checks `total` against 78.75 within 0.01, as
`pytest.approx(78.75, abs=0.01)` does, so rewriting 78.75 is reported as
`EXPECTED_VALUE_CHANGED`. The centre may stand on either side of the one
subtraction, and is read like any expected value, through parentheses and
TypeScript wrappers; either signed zero is the same centre. With no literal
centre (`Math.abs(total - expected)`, `Math.abs(d)`), or two, the whole
argument is the subject and there is no expected value. A subtraction inside
anything larger (a second additive operator, `||`, `in`, `as`) is not split.
Pairing keys on the subject, so an edited check pairs with itself, not with
whatever check happens to stand in its place.

The bound is recorded the way `pytest.approx(..., abs=eps)` records its
tolerance, and `TOLERANCE_LOOSENED` compares it as an exact decimal. It may be
a Number literal (read exactly from its digits, not as a binary float),
`Number.EPSILON`, `Number.MAX_VALUE`, `Infinity`, `Number.POSITIVE_INFINITY`,
a product of two of these, or a local `const`, `let` or `var` initialized to
one of them, each through parentheses and TypeScript's `as`, `satisfies` and
`!`. A TypeScript annotation between the name and its `=`, as in
`const eps: number = 0.01`, is skipped
([#240](https://github.com/taipei49314/checkwash/issues/240)). The bound of an
ordering matcher read this way is tolerance evidence only, never an expected
value. A
declaration ends where JavaScript ends it: at a `;` or `,`, or at a line break
where the next token cannot continue the expression, so `const eps = 0.01`
directly above `expect(...)` is read without a semicolon, and `+`, `.`, `(` or
`[` starting the next line continues it
([#196](https://github.com/taipei49314/checkwash/issues/196) 189.1). A name
that any write may have reached is unknown, not its initializer: every
assignment operator (`=`, `**=`, `%=`, `||=`, `??=` and the rest), prefix and
postfix `++`/`--`, a destructuring target, and a `for`-`in`/`of` head. A write
in any other function counts wherever it is written, because a hook, a helper
or a callback may run first; in the read's own function a write counts when it
comes first, or when a loop in that function runs both. A destructuring
declaration such as `const [eps] = [1e12]` shadows an outer `eps` with an
unknown value. A `toBeCloseTo(x, p)` precision and a hand-rolled bound are
compared as the same absolute bound, `10**-p / 2`, so `< 0.005` and
`toBeCloseTo(x, 2)` are equal, as Python's `places` and `delta` are (#196
190.3, below). A chai `closeTo` delta is recorded in the same `abs=` form (see
the chai section below).

A lower bound such as `Math.abs(d) > eps` asserts that two values differ, so
it is no tolerance. Its spellings still record the bound's direction, so a
comparison flipped from `<` to `>` is reported as a bound direction reversed,
`(< 0.01 -> > 0.01)`, and as an unverifiable replacement when either bound
cannot be read (#196 189.3). Both directions record what the magnitude
measures, so the two halves of a flip share a subject, and
`expect(cmp).toBe(true)` -> `assert.ok(cmp)` states the same bound. Since
189.2 the matcher spelling of a lower bound,
`expect(Math.abs(d)).toBeGreaterThan(eps)`, is read the same way, so its bound
is no longer an expected value; a lower bound's value is not compared in
either spelling.

A bound read on the base side that the head side cannot read is not the same
bound: rewritten into a call (`< 0.01` -> `< tolerance()`), past what an exact
decimal holds, or reached by a write. Like an unreadable `closeTo` delta, it is
reported as an unverifiable replacement (`ASSERT_WEAKENED`, "tolerance abs=0.01
-> a tolerance it cannot read"). A bound unknown on both sides replaces nothing
and stays silent.

Not read: negated or falsy spellings, conjunctions, relative or scaled
magnitudes, `**`, a literal whose exponent is past what an exact decimal holds
(such as `1e99999999999999999999`), imported or chained bounds, and a bound
behind an angle-bracket cast (`<number>0.01`). A later write in straight-line
code is taken to run after the read, so a function that runs twice (a helper
called again, `test.each`) and reads a bound its own later statement rewrote
is not followed. Two checks on one subject pair in order, so a check
inserted ahead of an edited one is paired with it, which can hide a widening
or report one. Two leftover checks that alignment pairs by position alone
are not compared when both moved, the subject and the literal centre alike:
a deleted check on one value and an added, looser check on another are a
substitution, which `EXPECTED_VALUE_CHANGED` and `ASSERT_SUBSTITUTED` report,
not one tolerance loosened (#196 189.2). A subject that moved alone, hoisted
into a local (`const t = total()`) or renamed, is the same check, and its
bounds are compared, as they are for every tolerance kind in both frontends.
Replacing a hand-rolled tolerance with `toBeCloseTo` or a chai `closeTo` on
the same subject compares the two bounds, in one unit. The source tests are in
[`tests/test_js_handrolled_tolerance.py`](../tests/test_js_handrolled_tolerance.py),
[`tests/test_abs_decomposition.py`](../tests/test_abs_decomposition.py) and
[`tests/test_fallback_tolerance.py`](../tests/test_fallback_tolerance.py).

Python reads the same shape with the builtin `abs`: `assert abs(total() -
78.75) < 0.01`, its reversed and `<=` forms, `self.assertLess(abs(...), eps)`,
`assertLessEqual`, `assertGreater(eps, abs(...))`, `assertGreaterEqual` and
`assertTrue(abs(...) < eps)`. The subject and centre are read as in
JavaScript, a numeric literal centre being the expected value, and the bound
is recorded as written, as an `abs=` tolerance, the way `pytest.approx`
records its own. A widened bound is `TOLERANCE_LOOSENED` and a tightened one
is no finding; before 189.2 the bound was the comparison's expected value, so
both were `EXPECTED_VALUE_CHANGED`. A file that binds `abs` itself (an import,
a definition, an assignment or a parameter) gets no such reading. A lower
bound, `abs(d) > eps`, `assertGreater(abs(d), eps)` or `assertTrue(abs(d) >
eps)`, is read for its direction, as in JavaScript (#224): what the magnitude
measures is its subject and a literal centre its expected value, it records
no tolerance, and its bound's value is not compared (#289). So a flip from
`<` to `>` is a bound direction reversed, `(< 0.01 -> > 0.01)`; before #224
the lower bound was a plain comparison, so the flip blocked as the centre
rewritten into the bound, and every change of its value, a tightening too,
as an expected value rewritten.

`assertAlmostEqual`'s `places` and `delta`, `pytest.approx`'s `abs=` and a
hand-rolled bound each state an absolute bound, and two of them in different
kinds are compared as that bound, places p as `10**-p / 2`, written from its
digits, as in JavaScript (#196 190.3). unittest passes `places=p` when
`round(a - b, p) == 0`, which is the bound `toBeCloseTo(x, p)` states. So
`places=7` -> `delta=7` reports a loosening from 5e-8 to 7, and so does
`delta=0.001` -> `places=1`; `delta=5` -> `places=3` is a tightening, and
`abs(x - c) < 0.01` -> `delta=0.01` the same bound, so neither is reported. A
relative tolerance (`rel=`, `pytest.approx`'s default) states no absolute
bound, so a bound rewritten into one is still compared as new slack, and so
is a pair with several tolerances at once. A negated comparison
(`assertNotAlmostEqual`, `!=` or `not` around `approx`) passes when the
values are far apart, so its tolerance orders the other way: it records no
tolerance, as in JavaScript, and a change of it is unknown rather than read
backwards. `== approx(x)` -> `!= approx(x)` is the polarity inversion that
`== 78.75` -> `!= 78.75` is
([#284](https://github.com/taipei49314/checkwash/issues/284)). The source tests
are in
[`tests/test_tolerance_absolute_bound.py`](../tests/test_tolerance_absolute_bound.py)
and [`tests/test_issue284_negated_approx.py`](../tests/test_issue284_negated_approx.py).

An assertion is an approximate comparison only where it states one
([#299](https://github.com/taipei49314/checkwash/issues/299)): `pytest.approx`
is an operand of the assertion's own `==`, `!=`, `in` or `not in`, or sits
inside one through a list, tuple, set or dict display; or that comparison is
a link of a chained comparison (`0 < x == approx(y)`), is conjoined with
`and`, or is asserted by `all(...)` over a comprehension, since each part
must hold. Anything else is read as a plain assertion:
`x == approx(y) or True` and `any(x == approx(y) for ...)` are truthy,
`(x == approx(y)) is not None` compares with None, and
`repr(approx(1.0)) == '1.0 ± 1.0e-06'` compares the string. A call that
receives an approx object, such as `operator.eq(x, approx(y))`, is read as
the call, as `operator.eq(x, 78.75)` is: checkwash cannot tell an operator
from any other function. The source tests are in
[`tests/test_issue299_approx_structure.py`](../tests/test_issue299_approx_structure.py).

### Python tolerance calls

Issue [#222](https://github.com/taipei49314/checkwash/issues/222) showed that
`assert math.isclose(total(), 78.75, abs_tol=1e-9)` was a truthy assertion
with no tolerance, so widening `abs_tol` to `1e3` passed with zero findings,
and numpy's and torch's assertion calls were no assertions at all. One table
now reads these calls as the approximate comparisons they are, at the
strength of `pytest.approx` and `assertAlmostEqual`:

| Call | Tolerances read | Left out, recorded as |
|---|---|---|
| `math.isclose(a, b)` | `abs_tol` as `abs=`, `rel_tol` as `rel=` | `abs_tol=0.0`, `rel_tol=1e-09` |
| numpy's `isclose(a, b)` and `allclose(a, b)` | `atol` as `abs=`, `rtol` as `rel=`, by keyword or as the fourth and third arguments | `atol=1e-08`, `rtol=1e-05` |
| `numpy.testing.assert_allclose(actual, desired)` | the same | `atol=0`, `rtol=1e-07` |
| `numpy.testing.assert_array_almost_equal(actual, desired)` | `decimal`, by keyword or as the third argument | `decimal=6` |
| `numpy.testing.assert_almost_equal(actual, desired)` | the same | `decimal=7` |
| `torch.testing.assert_close(actual, expected)` | `atol` as `abs=`, `rtol` as `rel=`, keyword only | unknown: the pair depends on the dtype (222.Q3) |

A default is recorded as numpy 2.3 and CPython state it, so a tolerance that
appears in the head is compared against the one the call had, as
`pytest.approx`'s default is. A call is read through the file's imports
(`import numpy as np`, `from numpy.testing import assert_allclose`,
`from math import isclose`), through `np = pytest.importorskip("numpy")`,
annotated or written with `:=`, and as `math`, `numpy` or `torch` when nothing
in the file binds that name. A name the file binds to two different things,
or also binds otherwise (a definition, an assignment), is not read.

`math.isclose` and numpy's `isclose` and `allclose` are predicates. They are
read in an `assert`, also through a call around them
(`assert np.isclose(a, b).all()`, `assert np.all(np.isclose(a, b))`,
`assert all(math.isclose(x, y) for x, y in pairs)`), and in `assertTrue`,
which is read as the call it wraps (222.Q2). numpy's and torch's assertion
functions are assertions written as statements, so deleting one is
`ASSERT_REMOVED`. Each call records the value it compares against as its
expected value (222.Q1): the literal one when only one of the two is a
literal, as `assertEqual` does, and otherwise the second (`b`, `desired`,
`expected`). So `math.isclose(total(), 78.75)` -> `math.isclose(total(), 75)`
is `EXPECTED_VALUE_CHANGED`, and the rules that read an assertion's subject
and expected value read these calls exactly as they read
`assertAlmostEqual(actual, desired)`.

`TOLERANCE_LOOSENED` compares the tolerances as it compares
`pytest.approx`'s: `abs=` and `rel=` loosen as they grow, and two or more at
once are compared kind by kind. numpy's `decimal` passes while
`abs(desired - actual) < 1.5 * 10**-decimal`, so it loosens as it shrinks, and
against another absolute bound it is compared as `1.5 * 10**-d`, its own
conversion, not unittest's `10**-p / 2`. So `decimal=6` -> `decimal=0` is a
loosening and `decimal=0` -> `decimal=6` is no finding, and
`math.isclose(x, y, abs_tol=1e-9)` -> `x == pytest.approx(y, abs=1e-9)` keeps
the absolute bound and drops the relative one, so it is no finding either. A
tolerance written as a name or an expression is recorded as written, as
`pytest.approx`'s is. A tolerance passed through `*args` or `**kwargs`, and
torch's omitted pair, cannot be read; a known tolerance replaced on the same
subject by one that cannot be read, such as
`torch.testing.assert_close(a, b, rtol=1e-5, atol=1e-8)` ->
`torch.testing.assert_close(a, b)`, is an unverifiable replacement
(`ASSERT_WEAKENED`), as in JavaScript.

Not read: a negated call (`assert not math.isclose(...)`, `assertFalse(...)`),
which passes when the values are far apart, so its tolerance orders the other
way and is not recorded, as in JavaScript and, since #284, for a negated
`pytest.approx` and `assertNotAlmostEqual`; other numpy and torch helpers
(`assert_approx_equal`'s significant digits, `assert_array_less`,
`assert_array_max_ulp`, torch's deprecated `assert_allclose`); a predicate
inside a comparison or a boolean operator
(`assert math.isclose(a, b) == True`, `assert isclose(a, b) and ok`); a name
bound to numpy by anything but an import or `pytest.importorskip`; and an
assertion call in a fixture or in a helper another file defines, which lend
the test their bare `assert`s only
([#286](https://github.com/taipei49314/checkwash/issues/286)). A call inside
`pytest.raises(AssertionError)` is read as positive, as unittest's assertion
methods are. A `decimal` rewritten into `assert_allclose`'s `rtol` and `atol`,
the migration numpy's documentation recommends, is a pair of several
tolerances against one, so it is compared kind by kind and reads as new slack
even where the new bound is tighter for the values compared. The source tests
are in [`tests/test_tolerance_calls.py`](../tests/test_tolerance_calls.py).

### chai expect chains and the assert interface

Issue [#180](https://github.com/taipei49314/checkwash/issues/180) found that
chai assertions were unrepresented: `expect(total).to.equal(78.75)` weakened
to `.to.exist` passed with only a coverage warning. chai's `expect` and
`assert` now resolve from `chai` imports and requires (named, renamed,
namespace and default), from Vitest's `expect` and `assert`, and for an
unimported global `expect`. An unimported `assert` keeps its Node default:
methods that both libraries spell the same cannot be told apart. Jest's own
`expect`, imported from `@jest/globals`, reads Jest matchers only: Jest's
`expect` has no `.to`, so a chai chain on it stays a coverage gap, and
`@jest/globals` exports no `assert`
([#198](https://github.com/taipei49314/checkwash/issues/198)).

An `expect(...)` chain is represented only when it ends in exactly one
terminal assertion. Language chains (`to`, `be`, `been`, `is`, `that`,
`which`, `and`, `has`, `have`, `with`, `at`, `of`, `same`, `but`, `does`,
`still`, `also`, and uncalled `a`/`an`) are ignored, `not` negates, and
`deep` makes `equal` a deep comparison. A property terminal may also be
called with at most a message argument, as dirty-chai allows. Each spelling
takes an existing rung; the strength lattice is unchanged.

| chai spelling | Form and rung | Expected-value evidence |
|---|---|---|
| `equal`/`equals`/`eq`; `assert.strictEqual` | `compare_eq`, EXACT_VALUE | scalar operand |
| `eql`/`eqls`/`deep.equal`; `assert.deepEqual`/`deepStrictEqual` | `compare_eq`, EXACT_STRUCT | scalar operand |
| `assert.equal` (coercive `==`) | `compare_eq`, EXACT_VALUE | scalar operand, as for Node's legacy `equal`; the `eq_loose` key carries the coercion |
| `.true`/`.false`/`.null`; `assert.isTrue`/`isFalse`/`isNull` | `compare_eq`, EXACT_VALUE | the implied literal |
| `.undefined`; `assert.isUndefined` | `compare_eq`, EXACT_VALUE | none |
| `.exist`/`.exists`; `assert.exists`/`isDefined` | `non_null`, NON_NULL | none |
| `.ok`; `assert(value)`, `assert.ok`/`isOk` | `truthy`, TRUTHY | none |
| `closeTo`/`approximately` in both interfaces | `approx`, APPROX | center; a positive call's delta, read exactly, is its absolute tolerance (`abs=`) |
| `include`/`includes`/`contain`/`contains`; `assert.include` | `membership`, PATTERN | none |
| `match`/`matches`; `assert.match` | `pattern`, PATTERN | none |
| `above`/`below`/`least`/`most` and their aliases; `assert.isAbove`/`isAtLeast`/`isBelow`/`isAtMost` | `compare_ord`, BOUND | the bound operand |
| `within` | `compare_ord`, BOUND | none |
| `lengthOf`/`length(n)`; `assert.lengthOf` | `type_shape`, TYPE_SHAPE | none |

Everything else is recorded with no strength
([below](#assertions-checkwash-does-not-read), #196 190.5) and stays visible
as a coverage gap: type checks (`a(...)`, `instanceof`), `property`, `keys`,
`members`, `oneOf`, `throw`, `satisfy`, `empty`, `NaN`, change assertions, the
`own`, `nested`, `any`, `all`, `ordered` and `length` flags, plugin words such
as chai-as-promised's `eventually`, a chain that continues after its terminal,
and negated assert methods (`notEqual`, `isNotOk`, `notExists`, ...). Deleting
one reports its removal, and so does replacing a represented assertion with
one; rewriting one is not judged. Plugins that overwrite a
core assertion word are not modeled. Should-style assertions
(`value.should.equal(...)`) are not scanned and produce no diagnostic.

The `.null` spelling is chai's `=== null`, so it shares `equal(null)`'s
EXACT_VALUE rung while Jest's `toBeNull()` keeps NON_NULL. The rungs differ,
but the predicate is the same (see [Predicate identity](#predicate-identity)),
so rewriting `.to.be.null` as `toBeNull()` is not reported, and neither is
`toBe(null)` -> `toBeNull()`. Scalar evidence keeps `0` and `-0` distinct
although chai's `===` accepts both.

A `closeTo` delta is the absolute bound a hand-rolled
`Math.abs(a - b) < bound` states, so it is recorded in the same `abs=` form
and read by the same exact reader (see
[Hand-rolled tolerances](#hand-rolled-tolerances)): a Number literal from its
digits, `Infinity`, `Number.EPSILON`, `Number.MAX_VALUE`, a product of two of
these, or a local name initialized to one (#196 190.4). Swapping one for the
other compares the two bounds, and a Vitest `toBeCloseTo(v, p)` precision
compares with either through the bound it enforces: `toBeCloseTo(v, 2)` ->
`.to.be.closeTo(v, 1)` and `.to.be.closeTo(v, Infinity)` report a loosening,
`.to.be.closeTo(v, 1)` -> `toBeCloseTo(v, 0)` does not. The delta is shown as
an exact decimal, so a delta written as an integer or with an exponent is
spelled differently than in v0.5.0 (`abs=1.0` -> `abs=1`, `abs=5e-07` ->
`abs=5E-7`), in the message and in the TOLERANCE_LOOSENED fingerprint of a
pair whose old side is such a delta. A delta checkwash cannot read is unknown;
see [Operand evidence](#operand-evidence).

Some edits are not reported. They are recorded here for a maintainer decision:

- A hand-rolled bound inside a chai assertion is not read as a tolerance.
  `expect(Math.abs(d)).to.be.below(eps)` records `eps` as a bound, so a
  literal widened there is reported as an expected-value change rather than
  a loosened tolerance; `assert.isTrue(Math.abs(d) < eps)` and chai's or
  Vitest's `assert.ok(Math.abs(d) < eps)` record nothing for it, so widening
  `eps` there produces no finding.
- A chai alias read from a member expression and then reassigned, such as
  `let check = require("chai").expect` followed by `check = wrap(check)`,
  produces no coverage diagnostic.
- The predicate-identity residuals listed in [Predicate identity](#predicate-identity).

`.to.not.exist` -> `.to.be.null`, `.to.not.be.undefined` -> `.to.exist` and
`.to.exist` -> `.to.be.ok` are proven strengthenings and are not reported.

### Predicate identity

Issue [#198](https://github.com/taipei49314/checkwash/issues/198) found that
the lattice gives different predicates one rung: `toBeNull()` and `.to.exist`
are both NON_NULL, `toBeLessThan(80)` and `.to.be.above(80)` both BOUND, so a
Jest matcher replaced by a chai spelling that asserts something else passed.
Each JS spelling below now records a predicate key, and `positive` says
whether it asserts that key or its negation: `toBeDefined()` asserts
`is_undefined` negatively, like `.not.toBeUndefined()`.

| Key | Spellings |
|---|---|
| `is_null` (`=== null`) | `toBeNull()`, `toBe(null)`, `.null`, `.equal(null)`, `assert.isNull`, `strictEqual(x, null)`, strict-mode `equal(x, null)` |
| `is_undefined` (`=== undefined`) | `toBeUndefined()`, `toBe(undefined)`, `.undefined`, `assert.isUndefined`; negated: `toBeDefined()`, `assert.isDefined` |
| `is_nullish` (`== null`) | coercive `assert.equal(x, null)` or `(x, undefined)`; negated: `.exist`, `assert.exists` |
| `truthy` | `toBeTruthy()`, `.ok`, `assert(x)`, `assert.ok`/`isOk`; negated: `toBeFalsy()` |
| `is_true`, `is_false` | `toBe(true)`, `.true`, `assert.isTrue`, `strictEqual(x, true)`, and the `false` spellings |
| `eq_strict` (`===`) | `toBe(y)`, `.equal(y)`, `assert.strictEqual`, strict-mode `equal` |
| `eq_loose` (`==`) | chai's `assert.equal`, Node's legacy `equal` |
| `lt`, `le`, `gt`, `ge` | `toBeLessThan` and the other ordering matchers, chai's `below`/`most`/`above`/`least` and their aliases, `assert.isBelow`/`isAtMost`/`isAbove`/`isAtLeast`, and a hand-rolled `Math.abs(d) < bound` in a truthy spelling (`assert.ok(...)`, `toBeTruthy()`, `toBe(true)`), keyed from the `Math.abs` side |

`toEqual`, `toStrictEqual`, deep equality, `toBeCloseTo`/`closeTo`,
membership, patterns, `within` and lengths record no key and keep the
lattice. An asymmetric matcher as the whole expected value of `toEqual` or
`toStrictEqual` is the predicate it states, not an equality:
`expect.anything()` is `!= null` (`is_nullish` negated, on the NON_NULL rung)
and `expect.any(Ctor)` a type check (TYPE_SHAPE, no key), so `toBe(78.75)` ->
`toEqual(expect.anything())` is a predicate widened (198.Q3).

The Python frontend records the bound keys (#224): `<`, `<=`, `>` and `>=`
with one comparator, read from the subject's side, so `80 > total()` is
`total() < 80`; unittest's `assertLess`, `assertLessEqual`, `assertGreater`
and `assertGreaterEqual`, with the same literal-side flip; and a hand-rolled
`abs(d) < bound` or `abs(d) > bound` in a bare `assert`, an ordering method
or `assertTrue`. The bound is recorded as one line of its source. So
`assert total() < 80` -> `assert total() > 80` is a bound direction
reversed, `< 80` -> `<= 80` a predicate widened, and `assertLess(total(),
80)` -> `assert 80 > total()` the same predicate. A chained range
(`0 < x < 60`), a comparison inside `assertTrue(...)`, and the equality,
identity and membership operators record no key and keep the lattice.

When both assertions of a pair carry a key on the same subject, ASSERT_WEAKENED
compares the two predicates instead of their rungs, from key and polarity
alone. A same or stronger predicate is not reported whatever the rungs say
(`.to.be.null` -> `toBeNull()`, `.exist` -> `.ok`, `.not.toBeNull()` ->
`.exist`). Otherwise the finding says what was established:

- **polarity inverted**: the same key with its polarity flipped,
  `toBeTruthy()` -> `toBeFalsy()`. Only this one says the test now proves the
  opposite.
- **contradicts**: no value passes both, `toBeNull()` -> `.to.exist`,
  `toBeTruthy()` -> `.to.be.false`; for bounds, **bound direction reversed**,
  `toBeLessThan(80)` -> `.to.be.above(80)`.
- **predicate widened**: the old predicate implies the new one,
  `toBeNull()` -> `.to.not.exist` (now also `undefined`), `toBe(78.75)` ->
  `assert.equal(x, 78.75)` (`===` -> `==`). The finding carries the honest
  rung drop, so MILD_WEAKENING holds a widening that stays inside the exact
  family at warn.
- **replaced; checkwash cannot verify the replacement is equivalent**:
  anything else the keys cannot establish, such as `.not.toBeNull()` ->
  `toBeFalsy()`.

The other three are never mild. The relation never reports an operand change:
a rewritten expected value is EXPECTED_VALUE_CHANGED's and a widened tolerance
TOLERANCE_LOOSENED's. It reads operands for two things the keys cannot say.
An `===` literal is placed among the presence keys: `toBe(5)` is defined, not
null and truthy, so `toBeTruthy()` -> `toBe(5)` is a strengthening and
`toBe(78.75)` -> `.to.be.undefined` a contradiction. When both sides state a
literal at one polarity, such as `toBe(5)` -> `.to.be.null`, the change is the
literal's and only EXPECTED_VALUE_CHANGED reports it. And when two bounds name
one bound (`toBeLessThan(80)` -> `toBeLessThanOrEqual(80)`, or `LIMIT` on both
sides), the values below, at and above it, and NaN, decide:
`<` -> `<=` is a widening, `<=` -> `<` a strengthening, and
`.not.toBeLessThan(80)` -> `toBeGreaterThanOrEqual(80)` a strengthening,
since the negated check also passes NaN.

The keys come in three families: presence (`null`, `undefined`, truthiness),
equality and bounds. Two keys of different families do not relate alone, so
such a pair, and a pair with an unkeyed side, keeps the lattice judgement
with `positive` in its documented meaning. A presence check (`toBeDefined()`,
`.exist`, `.not.toBeNull()`) beside an affirmative assertion of another kind
(`toEqual({...})`, `toContain(x)`, `toBe(expected)`) is not a polarity
change, so strengthening one into the other still passes.

An unkeyed pair whose polarity flipped is an inversion only on the same
subject (SPEC §4). A bare Python `assert` records no subject, and neither
does a `pytest.approx` comparison, so for such a pair what each statement
checks decides: the tested expression with its `not`s peeled, or the side of
the approx comparison that is not the approx call (#331). A negated
comparison (`!=`, `not in`, `is not`) anywhere in the statement is read in
its positive form, as a `not` is peeled, so `assert {'t': total()} == {'t':
pytest.approx(78.75)}` -> `!=` is an inversion (#284). `assert result.okay` -> `assert not result.okay` is an inversion,
and `assert result.okay` -> `assert not result.exception`, which checks
another attribute, is a replacement; both block without repair evidence.

Residuals of this reading:

- A change between `<` and `<=` (or `>` and `>=`) with two different bounds,
  or a bound checkwash cannot read, keeps the lattice judgement, so only the
  operand rules speak: a plain bound rewritten from `< 0.01` to `<= 0.005` is
  an expected-value change, and a hand-rolled tolerance tightened that way
  (`expect(Math.abs(d)).toBeLessThan(0.01)` -> `toBeLessThanOrEqual(0.005)`)
  passes. With a flipped `.not` on top as well, such as
  `.not.toBeLessThan(80)` -> `toBeGreaterThanOrEqual(75)`, it is reported as an
  unverifiable replacement.
- Keys of different families keep the lattice judgement: `toBeNull()` ->
  `toBe(expected)` and `toBeTruthy()` -> `toBeGreaterThan(0)` pass as
  strengthenings, and `toBe(5)` -> `toBeGreaterThan(3)` reports a strength
  drop.
- With `positive` in its documented meaning, a negated absence check
  (`.to.not.exist`, `.not.toBeDefined()`) rewritten as an affirmative
  assertion of another form (`.to.include(x)`, `toEqual(x)`) is no longer
  reported as a form and polarity change, and `toBeFalsy()` -> `toEqual(5)`
  now is.
Following the foundation precedent, the original inventory is unchanged. The
independent supplement
[`javascript_chai_mutations.json`](../tests/data/javascript_chai_mutations.json)
adds 39 losses, rewrites, tolerance increases and preserving or strengthening
controls written from the chai documentation. It runs in-process in
[`tests/test_js_chai.py`](../tests/test_js_chai.py); it is not yet part of
the CLI qualification below.

### Operand evidence

The evidence half of [#198](https://github.com/taipei49314/checkwash/issues/198)
keeps what an operand establishes across assertion APIs. A pair could read as
preserved while the old side's expected value or tolerance had no counterpart:
`toBe(78.75)` -> `assert.equal(value, 75)` passed because `==` recorded no
value (M2a-c), and `toBeCloseTo(v, 2)` -> `.to.be.closeTo(v, Infinity)` because
`Infinity` recorded no bound (M2f-h).

What each JS assertion records:

- **Expected values.** Every equality records its scalar operand, the
  coercive ones included (chai's `assert.equal`, Node's legacy `equal` and
  `deepEqual`); `toBeCloseTo` and `closeTo` record their center, and a
  hand-rolled `Math.abs(x - 78.75) < bound` its literal centre (189.2). The
  literal reader reads through parentheses and TypeScript wrappers (T4, T5),
  and `Number(<literal>)` folds to its value while `Number` names the global
  (T6, #226).
- **Bounds.** The ordering matchers, chai's bound words and
  `assert.isAbove`/`isAtLeast`/`isBelow`/`isAtMost` record their bound as a
  Python bound is recorded (198.Q2, Q4). A bound read as a hand-rolled
  tolerance is tolerance evidence only.
- **Tolerances.** See [Hand-rolled tolerances](#hand-rolled-tolerances) and
  the `closeTo` delta above.
- **`operand_source`.** Every expected value and bound also records its text,
  without comments, parentheses or TypeScript wrappers. It decides only
  whether two spellings state the same operand (`toBeLessThan(LIMIT)` and
  `.below(LIMIT)`), and which names a rewritten one reads. A hand-rolled bound
  records it only when the bound was read.

How the rules read them, as Python's do (198.IR amendment 2):

- EXPECTED_VALUE_CHANGED reports a literal rewritten into another literal,
  `toBeLessThan(80)` -> `.below(1e12)` included, and a name or call replaced by
  a different one: `toBe(EXPECTED_A)` -> `toBe(EXPECTED_B)` reports
  "expected call rewritten to a different call ['EXPECTED_A'] -> ['EXPECTED_B']".
  As in Python, the same names with a changed member (`config.total` ->
  `config.subtotal`) do not.
- A literal and a name or call follow one definition with Python since
  [#226](https://github.com/taipei49314/checkwash/issues/226)
  ([Expected provenance](expected-provenance.md#conversions-unevaluated-calls-and-javascript-226)).
  A folded `Number(<literal>)` is a literal: `toBe(78.75)` -> `toBe(Number(75))`
  (T6) reports "expected value rewritten 78.75 -> 75.0". A literal replaced by
  a call to a global outside the fold set or to a name no scope declares
  (`parseFloat('75')`), or such a call rewritten into another (`build(1)` ->
  `build(2)`), reports "expected value replaced by an expression checkwash does
  not evaluate". A literal replaced by what an import, a declaration or a
  declared function gives reports EXPECTATION_DEFINITION_CHANGED with the
  value resolved: `toBe(78.75)` -> `toBe(OTHER)` reads "78.75 -> ./total.OTHER".
- A name or call replaced by a literal is not read in JS: `toBe(EXPECTED)` ->
  `toBe(75)` passes, where Python reports it (#60).
  [#292](https://github.com/taipei49314/checkwash/issues/292) asks for a ruling.
- TOLERANCE_LOOSENED compares two known tolerances. A tolerance checkwash
  cannot read (`closeTo(v, delta())`, `toBeCloseTo(v, precision())`) is
  unknown, and a known tolerance replaced by an unknown one on the same subject
  is not the same tolerance (#196 190.4): ASSERT_WEAKENED reports "assertion
  replaced; checkwash cannot verify the replacement is equivalent (tolerance
  places=2 -> a tolerance it cannot read)", never mild.

Residuals of this reading:

- JS has no counterpart of Python's single-assertion restoration proof, so a
  bound tightened into an exact value reports its new value:
  `toBeLessThan(80)` -> `toBe(78.75)` is an expected-value change, where
  Python passes `x < 80` -> `x == 78.75`. Honest threshold edits
  (`toBeGreaterThan(0)` -> `toBeGreaterThanOrEqual(1)`) report as they do in
  Python.
- A tolerance unknown before the edit is not compared: `closeTo(v, delta())`
  -> `closeTo(v, 1e12)` or `closeTo(v, other())` produces no finding, as
  Python's unreadable tolerances do not.
- `expect.objectContaining`, `expect.stringContaining` and the other
  asymmetric matchers keep the equality reading; `expect.any(Number)` ->
  `expect.any(String)` is not compared.
- The JS false-positive cost of these reports is not measured; the JS/TS
  replay corpus measures it before the release that ships them.

### Assertions checkwash does not read

A call to a resolved assertion API whose predicate the scans above do not read
is recorded with no strength, as Python records `assertRaises` (SPEC §3,
[#196](https://github.com/taipei49314/checkwash/issues/196) 190.5). A throw
check is `raises`: `expect(fn).toThrow(RangeError)`,
`expect(promise).rejects.toThrow()`, `assert.throws`, `assert.rejects`, and
chai's `.to.throw()`, `assert.throws` and `assert.isRejected`. Anything else
is `unknown`: `expect(save).toHaveBeenCalledWith(78.75)`, `toHaveLength`,
`toMatchObject`, `toMatchSnapshot`, `.resolves`, `expect.assertions(n)`,
`assert.match`, `assert.notStrictEqual`, `assert.fail`, the chai words above,
and a negated throw check (`.not.toThrow()`, `assert.doesNotThrow`).

Deleting one is `ASSERT_REMOVED`, high without repair evidence. Rewriting one
is not judged, because its predicate is not read. A check rewritten into a
newly written strong one (`toHaveBeenCalledWith(78.75)` ->
`expect(save.mock.calls[0][0]).toBe(78.75)`) is a compensated removal, at warn.

What is not recorded:

- a lookalike: an assertion name imported from another module, shadowed, or
  written over (`assert.throws = () => {}`). Recorded, it would pair by text
  with the oracle it replaced.
- a call the scans read but left out for its arguments (`expect(x).toBe()`),
  a name node:assert does not export (`assert.okay`), a Jest matcher on chai's
  `expect`, and a chai chain on the `expect` of `@jest/globals`.
- a bare `expect(value)`, asymmetric matchers and registration (`expect.any`,
  `expect.extend`), a call inside another assertion's arguments, and a call in
  a nested function or outside a test unit.

Each recorded call stays visible as a coverage diagnostic (below), with a
reason that says its rewrite is not judged. The source tests are in
[`tests/test_js_unjudged_assertions.py`](../tests/test_js_unjudged_assertions.py).

## Make unrepresented assertion candidates visible

`checkwash check` scans both sides of changed JS/TS test files for bounded Node,
chai `assert` and `expect(...)` candidates. It compares their source positions
with assertions represented by the frontend. A candidate in a file with no
recognized test unit, or inside another assertion, can therefore still produce
a diagnostic.

Diagnostics appear on stderr in every output format and in terminal output.
SARIF includes them as tool execution warnings, separate from findings. A base
location is labeled `before`; it is not projected onto the current checkout.
Zero assertions alone do not produce a warning. Coverage warnings do not change
the tampering verdict, severity policy or exit codes. A candidate the frontend
records with no strength ([Assertions checkwash does not
read](#assertions-checkwash-does-not-read)) stays a warning whose reason says
its rewrite is not judged; deleting it is a finding because the frontend
recorded it, not because of the warning.

For a machine-readable report alongside the existing findings JSON:

```bash
checkwash check BASE..HEAD --format json --coverage-report coverage.json
```

The separate report uses UTF-8, LF, sorted keys and no timestamp. Its schema is:

| Field | Meaning |
|---|---|
| `checkwash_coverage_version` | `1`, independent of IR/findings versions |
| `run` | `base`, `head`, `checkwash_version` |
| `scope` | `javascript_assertion_candidates` |
| `status` | `incomplete` if there are gaps; otherwise `no_known_gaps` |
| `files` | Scanned `{path, side}` pairs, including files without candidates |
| `gaps` | `{path, side, line, column, callee, reason}` records |

`side` is `before` or `after`; lines and columns are one-based positions in
BOM-stripped, LF-normalized source. The report requires a file path (`-` is
rejected) so it cannot corrupt stdout's existing machine protocol. JSON findings
and emitted IR keep their existing shapes.

`no_known_gaps` means only that this bounded candidate scan found none. It is
not a completeness claim. File discovery follows the test runners'
zero-configuration defaults: `.test.*` and `.spec.*` JavaScript/TypeScript
files; every JavaScript/TypeScript file beneath a `__tests__/` directory and
exact `test`/`spec` filenames, JSX/TSX included (Jest's default `testMatch`);
and Node's default `test/` directories and `test-*`, `*-test`, `*_test` and
exact `test` filenames for JS/CJS/MJS/TS/CTS/MTS. Bun's `*_spec` filenames, and
`*_test` beyond Node's extensions, are tests only in a file whose own source
names Bun (a `bun:test` import) or Deno (a `Deno.test` call): Jest, Vitest,
Mocha and node:test do not collect them. Configured globs (`testMatch`,
`include`, `spec`) are not read. A path whose default role comes before `test` (guardrail,
CI, snapshot) keeps that role inside these layouts, and so does a path under a
`roles` glob for `ci`, `snapshot`, `lockfile` or `conftest` in the checkwash
config. Such a file is still a test: the test rules judge its units beside that
role's own rules ([#197](https://github.com/taipei49314/checkwash/issues/197)).
So `__tests__/__snapshots__/out.js` is a stored expectation, and any test units
it holds are judged as well. A real test kept under `expected/`, `golden/` or
`__snapshots__/` is a stored expectation too, so editing it reports
EXPECTED_VALUE_CHANGED unless the same diff changes production code, even when
the edit is honest. A shell shebang or a `Makefile` name prefix does not make a
test file a CI script, even when the file names a test runner.
Generated/build/dependency paths remain excluded.

A move is judged by the runner that runs the test
([#196](https://github.com/taipei49314/checkwash/issues/196), 186.7). The
moved file's base side names it by import (`vitest`, `@jest/globals`,
`node:test`, `bun:test`, or a `Deno.test` call); without one, the base side's
root `package.json` does when its dependencies name exactly one of `jest`,
`vitest`, `mocha` and `jasmine`. A move that runner's default discovery does
not collect is checked as removal from test coverage: under Vitest,
`x.test.ts` -> `__tests__/x.ts`, `spec.ts` or `test/x.ts`; under node:test,
`test/x.js` -> `x.spec.js`. A unit that reappears in such a file earns no move
credit, because it does not run there. When nothing names the runner, a move
is benign only if a Jest or node:test default still collects the destination,
so `x.test.ts` -> `__tests__/x.ts` stays benign on Jest-style globals. The
runners match names case-sensitively, so moves do too: `__TESTS__/x.ts` is
collected by none of them. A file the named runner does not collect by default
is collected by its configured globs, which are not read, so its moves are
judged as if no runner were named. A move between two collected test paths is
judged as an edit of the same test, whatever roles they hold:
`src/x.test.ts` -> `test/expected/x.test.ts`.

The scan resolves bounded static Node ESM/CommonJS imports, renamed and flat
destructured imports, simple local aliases, Jest/Vitest `expect` imports, and
chai's `expect` and `assert` (including Vitest's `assert` re-export).
Lexical declarations and function parameters can shadow those bindings, and
a name that any write may have reached is unknown, as in the hand-rolled
tolerance section above; a lookalike object cannot retain a real assertion's
strength. Unresolved assertion
candidates still produce diagnostics. Dynamic module names, arbitrary wrapper
functions, computed properties and template interpolations remain outside this
evidence. This is a bounded static scan, not complete JavaScript scope or
execution modeling. A project requiring broader coverage must review those
boundaries.

## Qualify the bytes that users run

The `assertion qualification` workflow runs the original 248 changes plus the
35 foundation changes through actual CLI invocations against temporary Git
commits, separately for source, a freshly installed wheel and a zipapp. Fixture
JavaScript is read, never executed. It checks findings and exit codes, including
a clean range and an invalid-ref engine error. A preserving case must have no
findings. The same additive suite is also used for the recommended Action engine
measurement; an older engine's missing coverage remains a failure. The 39 chai
records are not in this CLI qualification yet: they run in-process
(`tests/test_js_chai.py`), and the previous-release verdict gate runs only the
26 that expect a block (#196, ruling X.pr190-q4).

Receipts identify the source commit, source package hash and dirty flag,
artifact hash, reported version, suite hash and each case's result. Artifact
package bytes and the wheel actually imported by the isolated interpreter must
match the selected source. A stale build cannot pass merely because it reports
the same version. The release workflow repeats these checks before artifact
upload and PyPI publication; see [the release procedure](RELEASING.md).
The optional `inventories` receipt field records each input inventory's path,
file hash and mutation count, while `suite_sha256` identifies the combined
mutation inputs. Existing receipts and historical outcomes are not rewritten.

A separate job extracts the full recommended Action SHA from the README and
qualifies that exact installed engine against the current contract. It does not
claim to exercise the composite Action wiring; existing dogfood smoke tests do
that. The recommended v0.5.0 engine includes the fixes for the #172–#181
reports but predates the v0.6.0 work that followed them. Any failing case
stays visibly red with a receipt, not
waived or silently re-pinned. A candidate passing the contract therefore does not imply
the older recommended Action has gained the same coverage.

## Require candidate qualification before merging

This repository's `checkwash required` ruleset targets the default branch and
requires `checkwash` plus all three `candidate assertion contract (source)`,
`candidate assertion contract (wheel)` and `candidate assertion contract (pyz)`
checks. Candidate checks are bound to the GitHub Actions app, run on every pull
request without path filters, and must be current with the base branch. Their
names must remain in sync with the ruleset; renaming a workflow job requires
updating the corresponding required context.

The older recommended Action engine is a separate compatibility measurement,
not a substitute for candidate qualification. Any capability it misses in the
contract stays visible. A passing required check does not erase failures in other
release or compatibility checks. The downstream Action ruleset example retains
only `checkwash`, since consumers do not run this repository's development jobs.
