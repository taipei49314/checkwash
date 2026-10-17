# JS/TS reachability and tautologies (#429)

Three one-line test edits that the Python frontend blocks passed in a JS/TS
test with zero findings: a self-comparison (`expect(total).toBe(total)`), an
assertion parked under a constant-false branch, and a `return` before the
assertion. Each assertion stayed in the unit at its original strength, so no
rule fired. This page states what the JS/TS frontend now reads in their
place, and what it still does not. THREATMODEL rows 8, 10, 29 and 48 point
here for their JS/TS clauses.

The ruling (issue #429, 2026-10-14) splits the work into two changes. The
first rates an assertion that can never fail at SPEC §3's TAUTOLOGY rung. The
second reads which statements of a test callback run (SPEC §2b), so an
assertion it never reaches is not the test's.

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
  of it, and a `//` comment ends at any line terminator, U+2028 and U+2029
  included. Where the tokens cannot tell how JavaScript reads a `/` (right
  after a `}`, after a statement head such as `if (ok)`, or inside a
  template substitution), the operand is not read, and the assertion keeps
  its rung. Comments, parentheses, `x!` and a cast to one named type
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
  Python: `a + b * 1` keeps its `* 1`, and `x + -0` its `-0`. A cast to one
  named type binds as TypeScript binds it, so `total as number + 0` is
  `(total as number) + 0` and reads as `total`, while `0 + s as any * 2` is
  `((0 + s) as any) * 2` and keeps its `0 +`. The stripping
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

## Statements a test callback never reaches

One bounded walk reads the statements of each test callback's block body,
as the Python frontend reads a test function's body. An assertion it proves
the callback never reaches is not the test's assertion. Parking one there is
`ASSERT_REMOVED`, with the key a deleted assertion has.

### What is cut

- Everything after an unconditional `return` or `throw` in the same
  statement list: `return;`, `return` alone on its line (JavaScript ends the
  statement there), `throw new Error("skip")`. A `return` whose operand
  holds the assertion (`return expect(x).toBe(1)`) runs it first.
- A branch the folder below decides: the body of `if (false)`,
  `while (false)` and `for (init; false; update)`, and the `else` of
  `if (true)`.
- A block and the selected branch of a decided `if` pass their termination
  on: `{ return; }` and `if (true) { return; }` end the statements after
  them, as `if True: return` does in Python.
- Inside loop, `do`, `try`, `catch`, `finally` and labeled bodies the same
  rules apply, but their termination never flows out: a `return` in a loop
  body cuts the rest of that body and nothing after the loop. An `if` whose
  condition is unknown passes nothing on either, even when both branches
  return, as in Python.
- The walk never enters a function, arrow or class body, so the `return` of
  a helper or of an iterator callback (`rows.forEach(() => { return; })`)
  ends nothing in the test. An assertion in such a callback keeps its
  lexical reading (D-106).
- An expression statement of `&&` or `||` that its literal operand decides
  skips the assertion that is its last operand: `false && expect(x).toBe(1)`
  and `true || assert.ok(x)`. The statement must start where the walk proved
  the previous one ended, so its first token cannot continue the line
  before, and the assertion must run to the statement's end.

### What the folder decides

The folder is exact and reads literals only: numbers, BigInts, strings,
templates without a substitution, `true`, `false` and `null`; `!` and
parentheses; `&&` and `||` as Python's fold reads `and` and `or` (one false
operand decides an `&&` and one true operand an `||`, whatever the others
are, so `if (false && ready())` is dead); `===` and `!==` between literals;
`==` and `!=` between literals of one primitive type; `<`, `<=`, `>` and
`>=` between two numbers, two BigInts, two strings (by UTF-16 code units,
as JavaScript compares them) or two booleans; and
`undefined` and `NaN` only where they name the unshadowed global. Anything
else is unknown and the branch keeps its reading: a name, a `const` binding
(`const off = false; if (off)`), a call, arithmetic, `typeof`, `void`,
`Infinity`, a comparison that coerces (`1 == "1"`, `null == undefined`), a
chained comparison, `?:`, `??` and the comma operator. The liveness options
of a test declaration (`test.skipIf(...)`, `{ skip: ... }`) keep their own
reading.

### Where the walk stops

The walk reads statements from tokens, and the token stream leaves out
templates and regular expressions. Wherever it cannot prove where a
statement ends, it stops reading that statement list, and every assertion
after the stop keeps its reading:

- a line break next to a template or regular expression
  (`return /x/\n.test(...)`, a template spanning lines);
- an unpaired bracket, a call the frontend could only recover, or U+2028 or
  U+2029 anywhere in the callback, and text the token stream misreads as
  code anywhere in it: a template nested in another's substitution (each
  template is read again as the operand reader reads it, so a quoted `}` or
  a `//` comment in a substitution hides none, and one it leaves unread, such
  as a `/` in a substitution, stops the walk too), JSX (`<p>...</p>`, after a
  block too, or a TypeScript `<T>x` assertion), a `/` the mask reads as a
  division where JavaScript starts a regular expression (after a block, a
  statement head, an update or an operator, or at a line's start), a
  regular expression it reads where JavaScript may divide (after anything
  but an operator, a punctuator such as `(` or `,`, or a keyword such as
  `return` that is no property name), or an Annex B HTML-like comment
  (`<!--`, `-->`); such a callback is not walked at all;
- a dead body that is no block, when its end lies past a line break
  (`if (false) skip()` with a `{` block on the next line, which JavaScript
  runs; `x!`, `as Config` or an arrow's `}` at a line's end; `.5` or `[1]`
  at the next line's start): JavaScript or TypeScript may end the
  statement at that line break, so the body is not killed;
- a `with` statement, `import` and `export`, and a TypeScript-typed or
  generic function declaration (`function f(): T {}`);
- an expression-bodied callback (`() => expect(x).toBe(1)`), which has no
  statements.

### Not read

- `break` and `continue` cut nothing after them.
- A `switch` body is not read: a `return` in a case cuts nothing, and the
  walk steps over the `switch` and goes on after it.
- A `switch` on a literal that no case meets, and `for (... of [])`, are not
  folded, though Python folds an unmatchable `match` and `for _ in []`.
- `while (true)` and `for (;;)` without a `break` never end, but the
  statements after them are kept.
- Of `false && expect(a) && expect(b)` only the last assertion is dropped;
  a declaration or assignment (`const ok = false && expect(x)`), an
  assertion in parentheses (`false && (expect(x))`), and the ternary, `??`
  and comma forms keep their assertions.
- A test registered in dead code (`if (false) { it(...) }`) is outside this
  change (#429 Q9), and so is an imperative skip (`t.skip()`) in dead code,
  which still marks the test.

What the cut leaves alone:

- The catch evidence of #363 reads every assertion a callback spells, run or
  not, so its findings do not change (`docs/js-catch-swallowing.md`).
- The coverage inventory reads a cut assertion as represented, not missed;
  one recorded with no strength keeps its reason.

## Evidence

Prepared on a work machine, where no test or checkwash ran; CI runs the
tests. The acceptance sweeps the ruling asks for have not run:
`NOT_RUN：工作機規則（POLICY work-machine-local），the sweep runs where the owner approves it`.
Its false-positive cost is unmeasured.

[Catch boundary](js-catch-swallowing.md) · [Known issues on main](KNOWN-ISSUES-next.md)
