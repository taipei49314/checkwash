# JS/TS reachability and tautologies (#429)

Three one-line test edits that the Python frontend blocks passed in a JS/TS
test with zero findings: a self-comparison (`expect(total).toBe(total)`), an
assertion parked under a constant-false branch, and a `return` before the
assertion. Each assertion stayed in the unit at its original strength, so no
rule fired. This page states what the JS/TS frontend now reads in their
place, and what it still does not. THREATMODEL row 10 points here for its
JS/TS clause.

The ruling (issue #429, 2026-10-14) splits the work into two changes. The
first, described below, rates an assertion that can never fail at SPEC §3's
TAUTOLOGY rung. The second, which reads which statements of a test callback
run, is a separate change; until it lands, an assertion after a `return` or
under `if (false)` still counts as one the test runs.

## Assertions that can never fail

### On literals alone

An assertion whose subject as written and every operand its predicate reads
are exact literals is TAUTOLOGY, whatever it evaluates to. That holds in every
library the frontend reads: Jest and Vitest `expect` matchers, chai `expect`,
`should` and `assert`, node:assert, AVA and tap.

- `expect(1).toBe(1)`, `expect("a").toBeTruthy()`, `expect(null).toBeNull()`,
  `assert.ok(true)`, `assert.isTrue(true)`, `expect(true).to.be.true`,
  `(5).should.equal(5)`, `t.true(true)` and `t.ok(1)` are tautologies.
- So is one that always fails: `expect(1).toBe(2)` and `assert(false)`. It
  fails the run, so it hides nothing, but it checks no code either.
- The operands are the expected value, a bound, a tolerance
  (`toBeCloseTo(1.5, 2)`, `closeTo(1, 0.01)`) and a property name
  (`.property("total", 1)`). A message argument is no operand:
  `assert.ok(true, "always")` and `expect(1, "msg").toBe(1)` are tautologies.
- A literal is a number (`1`, `-1.5e3`, `0x1F`), a BigInt (`10n`), a quoted
  string, a template with no substitution, a regular expression, `true`,
  `false` or `null`, or an array or plain object of them
  (`[1, "a"]`, `{ total: 1 }`). They are read as JavaScript tokenizes
  them, so a `//` in a template or a quote in a regular expression is part
  of it. Comments, parentheses, `x!` and a cast to one named type
  (`as number`, `satisfies Total`, `as const`) are read through, and a sign
  belongs to a number. A cast to anything more (`0 as any || x`) leaves the
  operand whole.
- A name is never a literal. That includes `undefined`, `NaN` and `Infinity`,
  which a file can shadow, and a shorthand property, a spread, a hole or a
  computed key in a container. `expect(undefined).toBeUndefined()` keeps its
  rung.

### One operand on both sides

An equality or an inclusive bound whose two sides are one operand is
TAUTOLOGY, as `assert f(x) == f(x)` is in Python (THREATMODEL row 10):

- `toBe`, `toEqual`, `toStrictEqual`, `toBeGreaterThanOrEqual` and
  `toBeLessThanOrEqual`; chai `equal`, `eql`, `deep.equal`, `least` and
  `most`, and the assert methods `equal`, `strictEqual`, `deepEqual`,
  `deepStrictEqual`, `isAtLeast` and `isAtMost`; node:assert `equal`,
  `strictEqual`, `deepEqual` and `deepStrictEqual`; AVA `is`, `not`,
  `deepEqual` and `notDeepEqual`; tap `equal`, `not`, `same`, `strictSame`
  and their negations.
- A negated one (`expect(x).not.toBe(x)`) can never pass. It is no oracle
  either, and it reads as Python reads `x != x`.
- The two token sequences compare once comments, parentheses, `x!`, a cast
  to one named type and formatting are taken out of each (quoted strings in
  double quotes; templates and regular expressions as written, whitespace
  included), and the outer no-op arithmetic Python
  strips: `x + 0`, `0 + x`, `x - 0`, `x * 1`, `1 * x` and `x / 1`, again and
  again (`(x + 0) * 1`). Only the outermost operation is stripped, as in
  Python: `a + b * 1` keeps its `* 1`, and `x + -0` its `-0`. The stripping
  is Python's reading, not an evaluation: `x + 0` reads as `x` although
  JavaScript makes `-0 + 0` positive zero, which `toBe` tells apart, and
  `"a" + 0` a string.
- Nothing is evaluated. The subject may be any expression:
  `expect(total).toBe(total)` where `total` is awaited, a parameter, a
  property or a destructured name, and `expect(f(x)).toBe(f( x ))`.

### How it is recorded

A tautology keeps the subject, text, span and operand evidence it was read
with, so a finding on its own evidence keeps its identity: a removed
`expect(1).toBe(1)` keeps its key. A pair whose new side is a tautology is a
strength drop, so where the old reading was a keyed relation (a `.not` that
flipped: `toBe(27)` -> `.not.toBe(total)`), the finding is now the drop,
under another key. It records form `tautology`, strength
TAUTOLOGY, no predicate key and `positive=True`. Without a key, the predicate
relation (SPEC §3) never reads `toBe(27)` -> `toBe(total)` as two spellings of
one `eq_strict`, which is what let the self-comparison through.

The catch evidence of #363 and #431 is read before the key and polarity are
dropped. That proof (`docs/js-catch-swallowing.md`) reads the predicate and
polarity an assertion spells, never the TAUTOLOGY rating, so what it reports
does not change.

### What it changes

- A tautology in place of an oracle is a strength drop: `ASSERT_WEAKENED`,
  `EXACT_VALUE(90) -> TAUTOLOGY(10)` for `toBe(27)` -> `toBe(total)`. With no
  production change in the diff it blocks.
- As in Python, a self-comparison on a local bound to one call
  (`const sum = add(1, 2); expect(sum).toBe(sum)`) reports `ASSERT_WEAKENED`
  instead of `EXPECTATION_DEFINITION_CHANGED`.
- A tautology never counts as compensation (SPEC §5 D4, D5 and the
  split-or-rename budget): a literal-only test cannot pay for a deleted one.
- Its removal is still `ASSERT_REMOVED`, with the same key; the message says
  `strength TAUTOLOGY`.

### Not read

- Truthy spellings of a self-comparison: `assert.ok(x === x)`,
  `expect(x === x).toBe(true)`. The `x === x` NaN idiom is one of them.
- SPEC §5's `trivial` reading, a subject of literals and builtins only:
  `expect(String(1)).toBe("1")`. JS/TS has no reading of it yet.
- A name bound to a literal (`const one = 1; expect(one).toBe(1)`), and two
  names bound to one value.
- Self-comparison outside equalities and inclusive bounds: `toBeCloseTo(x)`,
  `toContain(x)`, chai `include(x)`, `toMatch`, `within(x, x)`.
- A spread on both sides (`assert.equal(...pair, ...pair)`) compares two
  elements, not one operand.
- Spellings that evaluate alike but read differently: `a.b` and `a["b"]`,
  the comma operator `(x, x)`, TypeScript's angle-bracket assertion
  `<number>x`, and arithmetic Python does not strip.
- A property's value compared with that property
  (`expect(order).to.have.property("total", order.total)`,
  `assert.propertyVal(order, "total", order.total)`) is no self-comparison:
  it still asserts that the property is there.
- A negated self-comparison records `positive=True`, as `x != x` does in
  Python, so paired with a negated check of a value
  (`.not.toBe(5)` -> `.not.toBe(x)`, or back) it reads as a change of form
  and polarity.
- An operand that is not a literal makes the assertion a real one, even where
  its outcome is decided: `expect(1).toBeCloseTo(1, places)`,
  `expect(1).to.be.within(0, limit)`, `expect(1).toEqual(expect.anything())`.
- The catch residuals of #431 are unchanged: the TAUTOLOGY rating adds no
  always-pass proof to a catch (`docs/js-catch-swallowing.md`).

## Evidence

Prepared on a work machine, where no test or checkwash ran; CI runs the
tests. The acceptance sweep the ruling asks for has not run:
`NOT_RUN：工作機規則（POLICY work-machine-local），the sweep runs where the owner approves it`.
Its false-positive cost is unmeasured.

[Catch boundary](js-catch-swallowing.md) · [Known issues on main](KNOWN-ISSUES-next.md)
