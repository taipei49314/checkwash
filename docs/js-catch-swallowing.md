# JS/TS synchronous assertion swallowing (#363)

The frontend supplies `BROAD_EXCEPT_ADDED` evidence when a new same-function
try/catch surrounds an already represented synchronous assertion and its
catch neither directly rethrows nor reaches a resolved assertion that is
not proved to always pass (#431, below). Empty, comment-only, return and
log-and-continue catches are covered, and so are catches whose only
assertions are proved always-passing (`true`/`false`/`null` operands, below);
other literal spellings are named residuals. The engine
compares the evidence as a multiset before and after; adding suppression or
removing a preserving rethrow can therefore report the existing rule.

This uses the existing bounded token, binding and assertion model. It does
not add a JavaScript parser, run target code, change severity, or give JS
production code repair credit. Catch binding renames, comments and spacing
do not change the evidence key. Equal-count replacement of one swallowing
site with another is a residual of the multiset comparison.

The synchronous channel excludes promise-completion assertions by their
resolved API and actual call chain, including Node, AVA and tap async methods.
Operands and literal strings containing `.resolves` or `.rejects` do not
change that classification. Cross-function propagation, awaited expressions,
unknown conditional control flow, loop/switch/with structure, nested try
effects, class evaluation, labeled statements, typed function declaration
headers and `finally` are outside scope. Literal true/false branches and
direct terminal statements are read from the owning function body so a
try proved dead within that owning body supplies no evidence. Parent
callback registration/invocation reachability is not propagated: inline
callback obligations remain lexical, as in the existing frontend. Traversal stops at 32 structural
levels and supplies no claim for deeper shapes. An unused nested function cannot donate its
throw or assertion as catch safety. Supported assertion recognition retains
the existing import and lexical-shadow rules.

Represented Chai should getters use their actual chain anchor, including
property, parenthesized and indexed subjects. An assertion shape whose
completion cannot be classified makes its handler unsupported; it is never
silently removed from catch safety while claiming the catch is supported.

Assertion and unsupported-operator positions are indexed per function owner;
outer callback statements do not rescan descendant function tokens. Deep
input safety and callback-size scaling have new remote regression proposals.
No performance measurement has been executed on the work machine.

New fixture labels and the precise capability text are review proposals
until accepted under the maintainer's preparation authorization. Existing
fixture expected outputs and protected policy/gate files are unchanged.

## Always-passing assertions in the catch (#431)

A catch counts as inspection only when it reaches an assertion that is not
proved to always pass. The proof is narrow. It covers a resolved Vitest/Jest
`expect`, node:assert (`assert`, `assert.ok`, `assert.strictEqual`, and
`assert.equal` in strict mode) or chai `assert` call (`ok`, `isOk`,
`isTrue`, `isFalse`, `isNull`, `isUndefined`, `isDefined`, `exists`,
`strictEqual`) whose operands are only `true`, `false` or `null`, with no
extra arguments, and whose represented predicate and polarity evaluate to a
pass. `expect(true).toBe(true)`, `expect(null).toBeNull()`,
`assert.ok(true)` and `assert.isTrue(true)` are proved; the catch that holds
only such assertions swallows the guarded failure.

An always-failing assertion stays inspection: `expect(true).toBe(false)` and
`assert(false)` are the "fail if we get here" idiom and never swallow.
Anything the proof cannot read keeps the existing exemption. The try side is
unchanged: an always-passing assertion inside the guarded block still counts
as a protected assertion, and the assertion's IR form and strength are not
changed by this rule. Since #429 an assertion on literals alone reads as
TAUTOLOGY inside a try as outside one (`js-reachability.md`); this proof reads
the predicate and polarity the assertion spells, which the frontend drops from
a tautology only after the proof has run, and never that rating.

Such a catch reports its own evidence text, `catch always-passing
assertion`. A catch that reaches no assertion keeps `catch assertion`,
exactly as in v0.7.0, and the two texts are compared separately. A
pre-existing literal-only catch therefore cannot offset a newly added
swallowing catch in the same test file, and an old empty catch cannot offset
a new literal-only one. The cost is that adding an always-passing assertion
to a catch that already swallows reports the new text.

Named residuals, which keep the exemption:

- number and string literal equality (`expect(1).toBe(1)`,
  `expect('x').toBe('x')`), `toEqual(true)`, `toStrictEqual(true)`, loose
  `assert.equal(true, true)` and `expect(undefined).toBeUndefined()`;
- a message argument (`assert.ok(true, 'caught')`,
  `assert.isTrue(true, 'msg')`, `expect(true, 'msg').toBe(true)`);
- a local bound to a literal (`const ok = true; expect(ok).toBe(true)`) and
  TypeScript wrappers (`expect(true as boolean).toBe(true)`);
- non-boolean truthiness (`expect(1).toBeTruthy()`);
- chai BDD (`expect(true).to.be.true`), AVA `t.true(true)` and tap
  `t.ok(true)`;
- assertions on the caught binding that cannot fail when the guarded
  assertion fails (`expect(e).toBeDefined()`, `toBeTruthy()`,
  `toBeInstanceOf(Error)`), and assertions on unrelated always-true state;
- the Python counterpart (`except Exception: assert True`), which is not
  covered by this rule.

Literal, message-argument and proved self-comparison spellings are expected
to close through a shared always-pass helper (#429), keyed on the evaluated
outcome, never on the TAUTOLOGY strength rating. #429's first change rates
them TAUTOLOGY but adds no such helper, so they stay residuals here. A catch holding only AVA or
tap `t.pass()` is already reported, because `t.pass()` is not an assertion.
Equal-count exchange of two `catch always-passing assertion` sites, like
that of two `catch assertion` sites, remains a residual of the multiset
comparison.

## Reproduction record (#363)

The pre-fix remote reproduction is source
`b29cb836a4e2ddc241f737bc71e2720dffd749a8`, run `38087693144`, attempt 1:
13 failing new expectations and 133 passing controls, zero errors/skips.
The raw failure and source-bound artifact are retained. This is a named
defect reproduction, not a population false-positive or detection-rate
measurement. New implementation heads require their own remote results.
