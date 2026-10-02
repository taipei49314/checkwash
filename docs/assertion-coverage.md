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
methods and lookalikes are recorded alongside supported APIs.

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
the existing lexical coverage, including iterator callbacks; this does not
prove that an arbitrary callee executes its callback. Vitest's optional second
`expect(actual, message)` argument is diagnostic text, not the asserted subject.

Preserving controls cover assertion messages, multiline formatting, equivalent
numeric and string spellings, truthiness strengthened to an exact check, and
explicit versus omitted default precision. Converting a legacy Node equality
check to strict equality and removing parentheses around a scalar are also
preserving controls. Each blocking case requires exactly
its stated rule, severity and verdict; preserving cases require no findings.
Ten of these controls were added during v0.4.2 release review: equivalent scalar
spellings cannot invent an assertion substitution or hide subject wrapping and
concrete input changes. Known scalar equality is shared by those consumers;
unknown and Python expectations retain their prior handling. The source tests
are in [`tests/test_js_foundation.py`](../tests/test_js_foundation.py) and
[`tests/test_js_scalar_consumers.py`](../tests/test_js_scalar_consumers.py).

This scope reads complete balanced calls and direct scalar expected arguments:
finite Number literals, quoted strings, booleans and `null`. It does not infer
expected values from objects, arrays, BigInt, non-finite numbers, variables or
arbitrary expressions. Node expected-value evidence is limited to `strictEqual`
and `deepStrictEqual`, including their `t.assert` forms. `equal` and `deepEqual`
retain their existing strength-only model because the bounded bindings do not
distinguish their strict and coercive import modes. `toBeCloseTo` precision
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

The bound is recorded the way `pytest.approx(..., abs=eps)` records its
tolerance, and `TOLERANCE_LOOSENED` compares it as an exact decimal. It may be
a Number literal (read exactly from its digits, not as a binary float),
`Number.EPSILON`, `Infinity`, `Number.POSITIVE_INFINITY`, a product of two of
these, or a local `const`, `let` or `var` initialized to one of them. The
declaration has to end before the assertion starts: at a `;` or `,`, or at a
line break followed by `const`, `let`, `var`, `test`, `it`, `return`, `import`
or `function`. A `=`, `+=`, `-=`, `*=`, `/=` or postfix `++`/`--` write before
the assertion, in its own function or an enclosing one, makes the name
unknown. In JS files a `toBeCloseTo(x, p)` precision and a hand-rolled bound
are compared as the same absolute bound, `10**-p / 2`, so `< 0.005` and
`toBeCloseTo(x, 2)` are equal. A chai `closeTo` delta is recorded in the same
`abs=` form (see the chai section below).

Not read: lower bounds such as `Math.abs(d) > eps`, negated or falsy
spellings, conjunctions, relative or scaled magnitudes, `**`, a literal whose
exponent is past what an exact decimal holds (such as
`1e99999999999999999999`), and imported, chained or TypeScript-annotated
bounds. A declaration without a semicolon that runs on into the next line's
statement, such as `const eps = 0.01` followed by `expect(...)`, is not read
either. The binding scan does not follow other compound writes (`**=`, `%=`,
`||=` and the rest), prefix increments, destructuring writes or writes inside
another function such as a `beforeEach` callback, so a bound changed that way
still reads as its initializer. A comparison flipped from `<` to `>` and a
rewritten expected value inside `Math.abs(...)` are not reported by this
reading. As with `toBeCloseTo`, bounds are compared on the pairs alignment
forms: when one edit changes a hand-rolled check and inserts another tolerance
check ahead of it in the same test, the position fallback can compare the
bounds of two different checks. Replacing a hand-rolled tolerance with
`toBeCloseTo` also changes the asserted subject; that change keeps its
existing handling. The source tests are in
[`tests/test_js_handrolled_tolerance.py`](../tests/test_js_handrolled_tolerance.py).

### chai expect chains and the assert interface

Issue [#180](https://github.com/taipei49314/checkwash/issues/180) found that
chai assertions were unrepresented: `expect(total).to.equal(78.75)` weakened
to `.to.exist` passed with only a coverage warning. chai's `expect` and
`assert` now resolve from `chai` imports and requires (named, renamed,
namespace and default), from Vitest's `expect` and `assert`, and for an
unimported global `expect`. An unimported `assert` keeps its Node default:
methods that both libraries spell the same cannot be told apart.

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
| `assert.equal` (coercive `==`) | `compare_eq`, EXACT_VALUE | none, as for Node's legacy `equal` |
| `.true`/`.false`/`.null`; `assert.isTrue`/`isFalse`/`isNull` | `compare_eq`, EXACT_VALUE | the implied literal |
| `.undefined`; `assert.isUndefined` | `compare_eq`, EXACT_VALUE | none |
| `.exist`/`.exists`; `assert.exists`/`isDefined` | `non_null`, NON_NULL | none |
| `.ok`; `assert(value)`, `assert.ok`/`isOk` | `truthy`, TRUTHY | none |
| `closeTo`/`approximately` in both interfaces | `approx`, APPROX | center; a positive call's finite delta is its absolute tolerance (`abs=`) |
| `include`/`includes`/`contain`/`contains`; `assert.include` | `membership`, PATTERN | none |
| `match`/`matches`; `assert.match` | `pattern`, PATTERN | none |
| `above`/`below`/`least`/`most` and their aliases, `within`; `assert.isAbove`/`isAtLeast`/`isBelow`/`isAtMost` | `compare_ord`, BOUND | none |
| `lengthOf`/`length(n)`; `assert.lengthOf` | `type_shape`, TYPE_SHAPE | none |

Everything else stays unrepresented and visible as a coverage gap: type checks
(`a(...)`, `instanceof`), `property`, `keys`, `members`, `oneOf`, `throw`,
`satisfy`, `empty`, `NaN`, change assertions, the `own`, `nested`, `any`,
`all`, `ordered` and `length` flags, plugin words such as chai-as-promised's
`eventually`, a chain that continues after its terminal, and negated assert
methods (`notEqual`, `isNotOk`, `notExists`, ...). Replacing a represented
assertion with one of these reports its removal. Plugins that overwrite a
core assertion word are not modeled. Should-style assertions
(`value.should.equal(...)`) are not scanned and produce no diagnostic.

The `.null` spelling is chai's `=== null`, so it shares `equal(null)`'s
EXACT_VALUE rung while Jest's `toBeNull()` keeps NON_NULL. In a Vitest file,
rewriting `.to.be.null` as `toBeNull()` therefore reports a weakening, as
`toBe(null)` -> `toBeNull()` already does. Scalar evidence keeps `0` and `-0`
distinct although chai's `===` accepts both.

A `closeTo` delta is the absolute bound a hand-rolled
`Math.abs(a - b) < bound` states, so it is recorded in the same `abs=` form
(see [Hand-rolled tolerances](#hand-rolled-tolerances)). The delta itself is
read only from a finite Number literal, through the same number reader as the
expected value, not from the hand-rolled bound's exact reader. Swapping one
for the other compares the two bounds, and a Vitest `toBeCloseTo(v, p)` precision
compares with either through the bound it enforces: `toBeCloseTo(v, 2)` ->
`.to.be.closeTo(v, 1)` reports a loosening, `.to.be.closeTo(v, 1)` ->
`toBeCloseTo(v, 0)` does not.

Some edits are not reported. They are recorded here for a maintainer decision:

- `assert.equal` carries no expected value, so rewriting its operand
  (`assert.equal(x, 78.75)` -> `assert.equal(x, 75)`), or replacing
  `.to.equal(78.75)` with `assert.equal(x, 75)`, produces no finding. Coercive
  `==` evidence would apply to Node's legacy `equal` as well.
- A presence or truthiness check rewritten as an exact absent or falsy value
  (`.to.exist` -> `.to.be.null` or `.to.be.undefined`, `assert.exists` ->
  `assert.isNull`, `.to.be.ok` -> `.to.be.false`) reads as a strength
  increase, and JavaScript expected-value evidence needs a literal on both
  sides. Jest's `toBeDefined()` -> `toBe(undefined)` has the same gap.
- In a Vitest file that mixes styles, `toBeNull()` -> `.to.exist` keeps the
  NON_NULL rung and polarity, so it is not reported. Some other Jest -> chai
  rewrites that change the predicate or the direction of a bound, or drop an
  expected value or tolerance, are not reported either: those that keep the
  rung and polarity, read as a strength increase, or leave the new side with
  no expected value or tolerance, for example `toBeLessThan(80)` ->
  `.to.be.above(80)` and `toBe(78.75)` -> `.to.be.undefined`; v0.4.2 reported
  them as removals ([#198](https://github.com/taipei49314/checkwash/issues/198)).
  A rewrite whose two sides both carry the fact (a literal, a negation or a
  finite delta) is still reported.
- A hand-rolled bound inside a chai assertion
  (`expect(Math.abs(d)).to.be.below(eps)`, `assert.isTrue(Math.abs(d) < eps)`,
  chai's or Vitest's `assert.ok(Math.abs(d) < eps)`) is not read as a
  tolerance, so widening `eps` there produces no finding.
- A `closeTo` delta written as `Infinity`, `Number.EPSILON`,
  `Number.MAX_VALUE` or a name records no bound, so widening a tolerance into
  one of those spellings, from a delta, a hand-rolled bound or a
  `toBeCloseTo` precision ([#198](https://github.com/taipei49314/checkwash/issues/198)),
  produces no finding. The hand-rolled spelling of the same edit is reported,
  except `Number.MAX_VALUE`, which the hand-rolled reader does not read
  either. The delta is read as a binary float, so a literal with more digits
  than a double keeps compares by its rounded value against a hand-rolled
  bound's exact digits.
- A chai alias read from a member expression and then reassigned, such as
  `let check = require("chai").expect` followed by `check = wrap(check)`,
  produces no coverage diagnostic.

Some honest edits are reported instead: `.to.not.exist` -> `.to.be.null` and
`.to.not.be.undefined` -> `.to.exist` change form and polarity, `.to.exist` ->
`.to.be.ok` falls from NON_NULL to TRUTHY.

Following the foundation precedent, the original inventory is unchanged. The
independent supplement
[`javascript_chai_mutations.json`](../tests/data/javascript_chai_mutations.json)
adds 39 losses, rewrites, tolerance increases and preserving or strengthening
controls written from the chai documentation. It runs in-process in
[`tests/test_js_chai.py`](../tests/test_js_chai.py); it is not yet part of
the CLI qualification below.

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
the tampering verdict, severity policy or exit codes.

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
`*_test` beyond Node's extensions, are not recognized: Jest, Vitest, Mocha and
node:test do not collect them. Configured globs (`testMatch`, `include`,
`spec`) are not read. A path whose default role comes before `test` (guardrail,
CI, snapshot) keeps that role inside these layouts, so
`__tests__/__snapshots__/out.js` is a stored expectation, not a test. A path
under a `roles` glob for `ci`, `snapshot`, `lockfile` or `conftest` in the
checkwash config keeps that role too, and so does a test file promoted to CI
because it has a shell shebang or a `Makefile` name prefix and names a test
runner (or a script that runs one). No test rule reads such a file, so
weakening or deleting its tests can pass
([#197](https://github.com/taipei49314/checkwash/issues/197)).
Generated/build/dependency paths remain excluded. Moving a test out of every
recognized layout, for example into a production path or a snapshot directory,
is checked as removal from test coverage.

The scan resolves bounded static Node ESM/CommonJS imports, renamed and flat
destructured imports, simple local aliases, Jest/Vitest `expect` imports, and
chai's `expect` and `assert` (including Vitest's `assert` re-export).
Lexical declarations and function parameters can shadow those bindings; a
lookalike object cannot retain a real assertion's strength. Unresolved assertion
candidates still produce diagnostics. Dynamic module names, arbitrary wrapper
functions, computed properties and template interpolations remain outside this
evidence. This is a bounded static scan, not complete JavaScript scope or
execution modeling. A project requiring broader coverage must review those
boundaries.

## Qualify the bytes that users run

The `assertion qualification` workflow runs the original 248 changes plus the
25 foundation changes through actual CLI invocations against temporary Git
commits, separately for source, a freshly installed wheel and a zipapp. Fixture
JavaScript is read, never executed. It checks findings and exit codes, including
a clean range and an invalid-ref engine error. A preserving case must have no
findings. The same additive suite is also used for the recommended Action engine
measurement; an older engine's missing coverage remains a failure.

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
that. The recommended v0.4.2 engine includes the callback and scalar-evidence
foundation but predates the v0.5.0 fixes for the #172–#181 reports, which the
contract does not cover. Any failing case stays visibly red with a receipt, not
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
