# Defence design against the 2026-08-11 red-team report

> **Status: C1 and C2 shipped in v0.1.16. Everything else is still proposed.**
> The two shipped sections keep their original text so the design can be read
> against what it actually became; each carries a **Shipped** note with the
> measured result. Nothing else here is implemented.
> Every section states what would have to be *measured* before it ships. A
> design that has not been run against the corpus and the decoy arms is a
> hypothesis, and this project has a long record of hypotheses about its own
> behaviour being overturned by the first measurement. Read the "How this gets
> falsified" line in each section as the real content.

Source: [`redteam-weaknesses.md`](redteam-weaknesses.md)
— the maintainer's own red-team report against v0.1.15, vendored verbatim and in
the language it was written in, because editing someone's attack report to match
the repository's prose is a way of softening it. Eight of
its ten items were already recorded in `THREATMODEL.md`; the value it added is
the **taxonomy**, which this document adopts because it predicts where the
next hole will be:

1. **Leave the visible oracle** — move the thing being checked somewhere no
   rule looks.
2. **Buy `warn`** — pay a small real cost for a de-escalator.
3. **Hit an identity or enumeration boundary** — exploit a list that knows
   four spellings.

## What was verified before designing anything

Section 6 of the report was tested rather than believed. Eleven cases, each
weakening a real assertion **and** the test runner, with no production change,
so a fully-sighted greenwash must block all eleven:

| runner file | verdict | |
|---|---|---|
| `Makefile` | block | baseline |
| `common.mak` | **pass** | ⚠ |
| `Makefile.include` | **pass** | ⚠ |
| `justfile` | block | baseline |
| `Justfile` | **pass** | ⚠ |
| `ci/justfile` | **pass** | ⚠ |
| `scripts/test.sh` + `\|\| true` | block | baseline |
| `if ! pytest; then :; fi` | block, CI weakening missed | |
| `pytest \|\| echo ok` | block, CI weakening missed | |
| `test.ps1` PowerShell swallow | block, CI weakening missed | |
| `test.bat` `exit /b 0` | block, CI weakening missed | |

**The report under-rates this at P2.** Those four `pass` results are not "a
missing CI finding". An unrecognised runner file is classified `prod`, greenwash
cannot parse it, so `prod_opaque_change` becomes true and the **whole diff**
loses E1 — the `ASSERT_WEAKENED` beside it drops from high to warn. The file
whose entire purpose is running the tests buys the exemption meant for
production code it cannot read. That is a complete bypass, and it is P0 here.

Causes are dull and specific: `_RUNNER_SCRIPT_SUFFIXES` has `.mk` and not
`.mak`; `_RUNNER_SCRIPT_BASENAMES` is exactly `{Makefile, makefile,
GNUmakefile}`; the `justfile` role glob has no `**/` prefix and is
case-sensitive.

---

## Group C first: identity and enumeration boundaries

Taken first because it contains the only measured full bypass, and because its
fix generalises.

### C1. Stop enumeration misses from *buying* anything (P0)

> **Shipped v0.1.16.** Both layers, as designed. Layer 2 became simpler and
> stronger than written here: the test is not "recipe-shaped and unparseable"
> but simply *does this file's content invoke a test runner* — no shape check
> at all, so it does not inherit the enumeration it exists to backstop. All
> eleven measured cases now block; the two over-reach guards
> (`runner_build_makefile_neg`, `runner_opaque_native_neg`) stay green.


Widening the list is the obvious move and it is the weaker half. The list will
always be four spellings behind the ecosystem; what must change is the
consequence of missing one.

**Two independent layers.**

*Layer 1 — widen, cheaply.* `.mak`, `Makefile.*` / `*.mk` / `*.mak` basenames,
`**/justfile` case-insensitively, `.justfile`, `Taskfile.yml`, `Rakefile`,
`dodo.py`, `tasks.py`. Enumeration, honestly labelled as enumeration.

*Layer 2 — the durable one.* A changed file that greenwash cannot parse **and**
that looks like a task recipe must not grant the opaque exemption. "Looks like
a task recipe" is decided by content, exactly as `_is_runner_script` already
decides ci-ness: tab-indented recipe blocks, `just`/`make` variable syntax, a
shebang, or an invocation of any known runner. Such a file is `unknown-runner`:
it does not become `ci` (so a legitimate build Makefile is still repair
evidence), but it is **excluded from the opaque-exemption denominator**.

This is the answer to *"a list that knew one spelling knew none; a list that
knows four knows four"*: the list still knows four, but a miss now costs a
missed CI finding instead of a free pass on every oracle rule in the diff.

- **Discriminator:** a Makefile that compiles a C extension has no runner token
  and stays `prod` with full repair-evidence weight. Only recipe-shaped,
  unparseable, *changed* files lose the exemption.
- **FP risk:** medium. Projects whose real production build is a recipe file
  lose an exemption they legitimately had. Measurable.
- **Residual:** a recipe file with no recognisable shape at all.
- **How this gets falsified:** re-run the eleven cases above (all must block);
  full 1800-commit sweep — starlette and flask both edit `scripts/*` and
  Makefiles, so any FP appears there; and the pydantic integration, which is
  the only corpus member with a genuinely opaque production build.

### C2. Per-dialect weakening tokens (P0, same round as C1)

> **Shipped v0.1.16.** Suffix-keyed swallow tokens plus two-sided checks for
> the dialects with no `set -e`: `$LASTEXITCODE` and `errorlevel` no longer
> inspected, modelled on the existing errexit check — which is the robust half,
> since it does not depend on spotting an added token.


`.ps1` and `.bat` are already reclassified to `ci`; the token table is
shell/YAML-shaped, so their weakening is invisible.

| dialect | swallow signals |
|---|---|
| PowerShell | `$ErrorActionPreference` set to `Continue`/`SilentlyContinue`, `-ErrorAction SilentlyContinue` on a runner call, a trailing `exit 0`, removal of a `$LASTEXITCODE` check |
| cmd | `exit /b 0` after a runner invocation, removal of `if errorlevel 1` |
| sh (missing spellings) | `if ! CMD; then :; fi`, `\|\| echo …`, `\|\| printf …`, `; true` |

Keyed on file suffix so PowerShell tokens are not hunted in `.sh`.

- **Discriminator:** same two-family model E6 already uses — a *swallow*
  introduced anywhere is weakening; a *narrowing* counts only when introduced.
- **FP risk:** low. `exit 0` at the end of a script that never ran a runner is
  not matched, because the ci role is content-gated first.
- **Residual:** enumeration again — paired with C1 layer 2 so a miss is cheap.
- **How this gets falsified:** the four dialect cases above must block; sweep
  for new findings on any `.ps1`/`.bat`/`.cmd` in the corpus (expected: none —
  which makes this a recall-only change with weak corpus evidence, and that
  must be *stated*, as it was for the v0.1.8 runner round).

### C3. Guard semantics, not guard identity (#54) (P1)

`if sys.version_info < (3, 14): pytest.skip(...)` → `if True: pytest.skip(...)`.
The marker name is unchanged, so there is no `markers_added` event, and the
guard is deliberately excluded from marker identity to keep allowlist
fingerprints stable across documentation-level refactors.

**Design:** keep the guard out of the *fingerprint* and put it into the
*delta*. `guards_weakened` already exists for the case where a guard's meaning
changed because a constant it names was edited (#59). Extend it to the case
where the guard's **text** changed on an existing marker: evaluate both guards
under the same constant-folding used for branch pruning, and emit
`TEST_DISABLED` when the before guard discriminates and the after guard is
always true.

- **Discriminator:** a guard that goes from one real condition to another real
  condition is silent; only *discriminating → always-true* fires.
- **FP risk:** low; this is the same shape as #59, which fired zero times.
- **Residual:** a guard that becomes always-true only for values greenwash
  cannot fold.
- **How this gets falsified:** the #54 shape must block; the #59 fixtures must
  stay green; **fingerprint stability must be re-checked across 240 commits**,
  because the whole reason the guard is not in the identity is allowlist
  stability, and this design is only safe if that stays true.

### C4. Collection control by resolved path set (#81 / #83) (P1)

`collect_ignore.append(...)` on a conftest that already had collection control
produces no marker event; `collect_ignore` inside an `except ImportError:`
handler is not walked at all; `collect_ignore[:] = [...]` has a non-`Name`
target.

**Design:** stop comparing marker names and compare the **set of paths a
conftest removes from collection**, base side against head side. Walk the whole
module including handler bodies; accept `append`/`extend`/`+=`/slice
assignment/direct assignment. Each entry carries its enclosing guard, as
`collect_ignore` entries already do, so a real optional-dependency gate is
still a compat gate.

- **Discriminator:** the set grew, unguarded → tests stopped being collected.
- **FP risk:** low-medium; the guard machinery is what keeps
  `try: import redis / except ImportError: collect_ignore.append(...)` silent,
  and that pattern is common.
- **Residual:** paths computed at runtime (globs built from variables).
- **How this gets falsified:** #81 and #83 shapes must block; attrs
  `61e8179545` and `bb45938ab9` — the two real compat-gate conftests in the
  corpus — must stay silent.

---

## Group A: leaving the visible oracle

### A1. The expectation's *definition* changed (#86a) (P0)
> **Shipped v0.1.19, at `info`.** The threshold in the falsification line
> below was met and acted on: the sweep added **12 blocks** (36→48,
> 2.00%→2.67%), so it does not gate. Two sampled false positives had
> obvious credits — repair evidence reaching through a local helper (rich
> `1c5e03eb32`), and D9 `DEPENDENCY_DRIFT` (starlette `100f05a66b`) —
> and adding them until the count looked acceptable would have been
> fitting the rule to twelve known commits. They get their own round.
> Re-swept at `info`: 36→36, no verdict moved, 24 info findings. D-037.


The highest-value item in the report and in my own verification, because it
looks exactly like a refactor and the assertion line is byte-identical:

```python
- expected = round(sum(items) * (1 + TAX), 2)
+ expected = round(sum(items), 2)
  assert invoice_total(items, TAX) == expected
```

`EXPECTED_VALUE_DERIVED` requires the before-side expectation to have been a
*literal* — "the transition from a literal is the signal" was the design, and
that framing is precisely what leaves this open.

**Design.** The IR must carry more than dependency *names*: for each locally
bound name, record a normalised hash of its defining expression. `UnitSide`
gains `bindings: dict[name, BindingInfo(deps, expr_hash)]`. New rule
`EXPECTATION_DEFINITION_CHANGED`: an aligned pair whose assertion text is
unchanged, whose subject is unchanged, and whose expectation resolves to a
local binding whose `expr_hash` differs between the sides.

- **Discriminator vs. a legitimate expectation update:** none at the syntax
  level — and that is the point. It routes through repair evidence like every
  oracle rule: warn on its own, high only when no production change in the diff
  explains it. A genuine expectation update travels with a production change;
  this attack's whole purpose is not to make one.
- **FP risk: the highest of anything here.** Tests legitimately rewrite
  computed expectations during refactors. This is the one design in this
  document I expect the corpus to punish.
- **Residual:** an expectation computed in a fixture or helper *outside* the
  unit stays invisible (that is A5).
- **How this gets falsified:** fixture from `scratchpad/r84f` must block; then
  the full sweep. **If this adds more than a handful of blocks it does not ship
  as a blocking rule** — it becomes `info`, or ships behind an opt-in strict
  profile. Deciding that after the sweep, not before, is the whole discipline.

### A2. Subject laundering beyond containment (#84 / #86d) (P0)

Three shapes, one missing capability plus one ownership bug.

*Hoisted to the previous line.* `got = encode(s).replace(...)` then
`assert got == "…"`. **Design:** resolve the subject through local bindings the
way the expectation already is — add `left_depends_on` and, more importantly,
apply `SUBJECT_NORMALIZED`'s structural containment to the subject's
*resolved defining expression* rather than to the bare name. No new rule; the
existing one simply stops being blinded by one level of indirection.

*The argument is wrapped, not the subject.* `f(x)` → `f(normalize(x))`.
**Design:** containment at argument positions — same callee, same arity, and
every argument either equal to or containing its counterpart.

*The hand-off hole (#86d).* `ASSERT_SUBSTITUTED` defers a wrapped subject to
`SUBJECT_NORMALIZED`; `SUBJECT_NORMALIZED` declines because the expectation
moved. **Design (one line):** only defer when the expectation is genuinely
unchanged. This is the cheapest item in the document and closes a hole that two
rules each believed the other owned.

- **FP risk:** medium for the resolved-subject change (it makes an existing
  rule see more), low for the hand-off fix.
- **How this gets falsified:** the three shapes above and the informed arm's
  `percent_encode` task must block; sweep; and — because this changes what
  `SUBJECT_NORMALIZED` sees — the **differential classifier test** from the
  v0.1.14 verification must be re-run, since that rule fired zero times on 1800
  commits and any new firing is a real change in behaviour.

### A3. unittest parity (#86b) (P1, cheap)

`left_names` / `right_depends_on` are populated only in the `ast.Compare`
branch; `_classify_unittest_call` leaves them empty, so
`EXPECTED_VALUE_DERIVED` is structurally dead on every unittest assertion.

**Design:** populate them in `_classify_unittest_call` from the two call
arguments, applying the same literal-side flip that decides subject from
expectation. Mechanical.

- **FP risk:** low, but not zero — it changes nothing about pairing, only
  enables an existing rule on a new spelling.
- **How this gets falsified:** the 84a cheat written in unittest form must
  block; the corpus contains **0 `self.assert*` assertions out of 140,509**, so
  the sweep has no power here and that must be said out loud rather than
  reported as "no regressions".

### A4. Subject-less assertions (#86e) (P1)

`ASSERT_SUBSTITUTED` requires a subject on both sides, which exempts the truthy
form — the most common assertion shape in Python suites.

**Design:** give the truthy form a subject (the whole asserted expression) and
`isinstance(x, T)` a subject (`x`). Then narrow the guard from "either side
lacks a subject" to "either side is `raises`/`approx`", which is the only case
the guard was ever justified by (the `pytest.raises(match=)` fold).

- **FP risk: this one is sneaky.** `left` participates in stage-2 pairing
  `(form, left)`, so giving truthy assertions a subject **changes how
  assertions pair**, everywhere. That is a far larger blast radius than the
  rule being fixed.
- **How this gets falsified:** the differential classifier harness from the
  v0.1.14 verification, extended to compare `UnitDelta` pairings and not just
  classifications. If pairings move on real code, this design is wrong and the
  guard should instead be narrowed to `raises`/`approx` **without** giving
  truthy a subject.

### A5. Oracles behind custom helpers (~~P2, partial by nature~~ → **P0**, [#37](https://github.com/taipei49314/greenwash/issues/37))
> **Shipped v0.1.26, within the pre-registered thresholds.** Measured on four
> corpora at once: attacks 12/40 → **19/40**, a same-day disguised-extraction
> arm **28/40** at first contact, honest-refactor FPs 20/30 → **17/30**, the
> faithful-extraction arm 16/30. Both acceptance lines held — the refactor
> corpus improved rather than merely not-worsening, and the sweep delta is in
> the release notes. The prototype's "10" was itself a miscount (three cases
> were vacuous-subject edits, their own family now — THREATMODEL 91a); the
> `inherited` flag and the both-directions slot rule are in D-044. The
> lattice-weaker-extraction FPs are **kept**: that transition is what blocks
> 25 of the 28 disguised attacks.
> **The P2 ranking below was mine, it had no measurement behind it, and it was
> wrong.** Measured 2026-08-13: of 40 informed adversarial cases, greenwash
> blocks 12 and **28 escape**, and they are one root cause — this one
> (`benchmarks/tamper/`, THREATMODEL 91). `assert_sum(add(2, 3), 5)` is a
> *call*, so the unit records zero assertions; stop invoking the helper and
> nothing was removed or weakened, while `assert callable(assert_sum)` in its
> place registers as an assertion *added*. By the strength lattice the test got
> stronger.
>
> "Partial by nature" was also half wrong. Roughly 12–16 of the 28 are
> statically decidable — an oracle defined but no longer invoked, a mixin
> dropped from a `TestCase`, a fixture that stops being `autouse`, a
> `parametrize` table emptied, the real assertion wrapped in
> `pytest.raises(AssertionError)`. The genuinely undecidable half is different
> from what this section guessed: it is not depth, it is **subverted
> semantics** — `__eq__`/`__bool__`/`__contains__` that always return true, an
> `__exit__` that swallows, a no-op `TestResult`. Those need execution, and the
> honest answer there is mutation testing, not a 22nd rule.
>
> The framing below — "expansion to a depth of one" — is also too small. The
> right change is to the IR's question: not *which `assert` statements are in
> this unit* but **which assertions can this collected test reach**. See #37.

`assert_invoice_ok(total)` in `helpers.py`, then the test stops calling it or
calls it with a constant. The frontend understands bare `assert`, curated
unittest methods and some `pytest.raises`; it does not understand hamcrest, a
hand-written `check_eq`, or an assert inside a fixture.

**Design, replacing the "expansion to depth one" sketch this section used to
carry.** `UnitSide.assertions` stops meaning *"the `assert` statements lexically
inside this function"* and starts meaning **"the assertions this unit
executes"**:

- its own direct asserts, excluding those inside nested scopes it never calls —
  today's `ast.walk` counts an assertion in an uninvoked nested `def` as live,
  which is the whole of case 020;
- plus the direct asserts of same-file functions, lambdas, classes and
  `@contextmanager`s it **invokes**, followed through the file's own call graph
  to a stated depth.

Two definitions carry the design, and both were corrected by the prototype
rather than by argument:

*Reaching means invocation, not mention.* `callable(assert_sum)`,
`hasattr`, `inspect.getsource(f)` and `f.__name__` all name the oracle without
running it — that is precisely the edit these attacks make. Counting a bare
`Name` argument as a call hides case 001.

*Construction is not invocation.* `partial(boom, …)` binds; the call happens
when the partial is called. `checking(x, y)` builds a `@contextmanager`
generator; the post-yield assert runs only under `with`. Modelling either as
immediate invocation hides 036 and 004.

- **Measured value, before writing the detector: 10 of the 28 escapes**
  (001, 003, 004, 012, 013, 020, 022, 029, 034, 036). Not the 12–16 first
  estimated from the taxonomy — that estimate came from the generator's
  summaries rather than from the diffs, and prototyping it against all 40 cases
  is what corrected it.
- **The signal that does *not* work, recorded so it is not re-proposed:** "the
  unit's oracle no longer reaches production". It fails on 012, 020 and 036 once
  local bindings are resolved — in 020 the assertion still names `multiply`, it
  simply never runs. Reachability is the right axis; production-reachability is
  not.
- **FP risk: the highest in this document, above A1's.** This makes *every*
  existing oracle rule see more assertions. A helper wrongly credited to a unit
  invents assertions that were never there, and a call graph that over-resolves
  turns one legitimate refactor into a fleet of `ASSERT_REMOVED`s.
- **Added 2026-08-13, still before any detector code: the baseline says this is
  not only a recall change.** A corpus of 30 legitimate refactors — each
  shipping production twice so four pytest runs prove both sides still catch the
  bug — measures the *current* build at **20 false positives out of 30**
  (`benchmarks/refactors/`, THREATMODEL 92). Eight of them are `ASSERT_REMOVED`
  fired because the assertion moved into a helper, a `conftest.py` or a fixture
  teardown: **the same blindness that lets 28 of 40 attacks through**. So the
  question this round answers is not "how much precision does recall cost" but
  "does modelling reachability improve both numbers at once". A second
  acceptance criterion follows from that, fixed here: **the refactor corpus must
  not get worse, and the eight `ASSERT_REMOVED` cases are the ones to watch.**
  The sweep threshold below is unchanged.
- **Residual, stated not implied:** the helper in another module; oracles inside
  string literals (038); and the family this cannot touch at all — a syntactic
  `assert` whose *meaning* was subverted (`__eq__`/`__bool__`/`__contains__`
  always true, a swallowing `__exit__`, a no-op `TestResult`), plus computed
  zero-runs (an exhausted iterator, an unscheduled coroutine). Those need
  execution, and mutation testing is the honest answer rather than a 22nd rule.
- **How this gets falsified, and the severity threshold, fixed here before a
  line of detector code exists:** the ten cases above must move from authorised
  escape to blocked in `benchmarks/tamper/expected.json`, and no case that
  blocks today may stop blocking. Then the 1800-commit sweep, every new block
  reconciled by reading the diff. The budget is the roadmap's T1 DoD, the same
  one A6 used: **ΔFP ≤ 0.3pp = 5 commits of 1800.** More than five new blocks
  judged false and this does **not** ship as a blocking change — the reachable
  set still ships (it is a truer IR either way, and it fixes the uninvoked-
  nested-assert bug), but the rules that consume it stay at their current
  severity and the difference is reported at `info` until a later round earns
  the promotion.
- **And the thing that is not allowed, again:** buying the count back by
  narrowing the call graph until the number fits. Each narrowing must be
  justified by a semantic argument — "construction is not invocation" is one —
  not by which corpus commits it silences.

### A6. The test patches the thing it asserts about (T1.4 / #11) (P1)
> **Shipped v0.1.25, blocking — but not for the reason the sweep number
> suggests.** 36 → 36 blocks, and the rule fired **zero** times on 1800
> commits, so that is not a measured false-positive rate. The instrumented run
> is what settled it: 735 unit-sides carry a patch, 38 of those in units the
> diff created, and **one** newly added patch lands in a test that already
> existed — denied at the hygiene filter. Humans write the mock *with* the
> test. The pre-registered budget below is honoured against a measured **base
> rate of the precondition**, ceiling 0.06pp, not against an FP count this
> corpus cannot produce. The same probe found the rule's own hole (the subject
> behind one local) before release. D-043, THREATMODEL 90.

Ranked **#2** on the post-P0 residual list — ★★★★★ silence, and the one item
there whose difficulty column says "假陽性極多" in my own handwriting.

```python
def test_invoice():
    monkeypatch.setattr(billing, "invoice_total", lambda *a: 105.3)
    assert invoice_total(items, 0.05) == 105.3   # checks the stand-in
```

`CONFTEST_PATCHES_PROD` sees none of this: it only reads conftest files. Prod
and the assertion line can both stay byte-identical.

**The problem this design has to solve is not detection, it is discrimination.**
In a conftest, patching first-party code is exceptional — one autouse fixture
swaps the module under test for the whole suite. Inside a test function it is
*the normal way to write a unit test*, and the corpus is six libraries that do
it constantly. "New first-party patch target in a test unit", the acceptance
line in the issue, taken literally, fires on every commit that adds a mock.

**Design.** Three conditions, all required:

1. **The unit existed before.** A brand-new test that mocks is a test that was
   written with a mock. Only an existing unit can have a stand-in *inserted
   under* it.
2. **The patch is new on the after side** — same base-vs-head comparison the
   conftest rule already does.
3. **The patched attribute is reached by this unit's own assertions.** This is
   the discriminator, and it is the whole design. `setattr(billing,
   "invoice_total", …)` under `assert invoice_total(…) == 105.3` replaces the
   subject of the oracle. `setattr(app.config, "RETRIES", 1)` under an
   assertion about rendering makes the test fast and is not reported.

Condition 3 is what separates this from the naive rule, and it is checkable
from IR that already exists (`left_names`, and the callee names of the asserted
subject).

- **Discriminator vs. legitimate mocking:** the assertion has to be about the
  patched name. Hygiene stubs — time, network, env, a slow internal helper — are
  reached by the test but not by its oracle.
- **FP risk: high, and higher than A1's.** A1 could at least claim the edited
  binding *was* the expectation; here the corpus is full of first-party patching
  by construction.
- **Residual, expected to stay open:** `patch` targets built at runtime; a stub
  installed by a fixture the unit merely requests; `respx`/`responses` and other
  HTTP mock dialects; and the whole class where the patched name reaches the
  assertion only through a helper. Stated, not hidden.
- **How this gets falsified — and the severity threshold, fixed here before a
  line of the detector exists:** the attack shape above must block; the four
  legitimate shapes (stdlib stub, third-party stub, brand-new mocking test,
  first-party attribute no assertion touches) must stay silent. Then the full
  1800-commit sweep, with **every** new block reconciled by reading the diff.
  The budget is not a fresh number invented today — it is the one the roadmap
  already wrote down in the T1 DoD: **ΔFP ≤ 0.3pp without a written
  justification**, which on 1800 commits is **5 commits**. So: more than five
  new blocks that reconciliation judges false, and this **does not ship as a
  blocking rule** — it becomes `info`, exactly as A1 did, and the honest
  sentence goes in the release notes instead of a tuned threshold.
- **And the thing that is not allowed:** buying the count back by adding
  credits until it fits. A corpus commit that needs a credit gets its own round
  with its own evidence. Fitting a rule to the handful of commits that
  embarrass it is how a rule ends up passing exactly the diffs it was shown.

---

## Group B: buying `warn`

### B1. The opaque blanket, per-relationship instead of diff-global (P1)

One unreadable production file suppresses E1 for **every** oracle finding in
the diff. This is the largest structural hole on the *attack surface*.

Two true things that must be stated together, because stating either alone
misleads: on this corpus the blanket is granted 32 times and is load-bearing
**zero** times — disabling it entirely moved the block set 35 → 35 — *and* six
pure-Python repositories are exactly where it does nothing. Low incidence is
not low exploitability.

**Design:** the exemption stops being diff-global. An opaque production file
suppresses E1 only for findings in test files **related** to it: same top-level
package, or the test file imports something the opaque file's directory
provides. An unrelated opaque file — `scripts/deploy.sh`, an unrelated
template — buys nothing.

- **Discriminator:** relatedness, computed from the same import machinery
  repair evidence already uses.
- **FP risk:** real, and pointed at exactly the projects the blanket exists
  for. A C extension changing under a pure-Python test is *related* by package
  and still credits.
- **Residual:** an attacker edits an opaque file inside the same package. The
  cost of the attack rises from "any unreadable file anywhere" to "an
  unreadable file in the package under test", which is the point.
- **How this gets falsified:** the sweep will show ~nothing (the blanket is
  load-bearing zero times here), so **the corpus cannot validate this** and
  saying otherwise would repeat the v0.1.8 mistake. The real evidence is
  pydantic, whose opaque share is 20.3% because of its Rust core. This design
  does not ship on corpus evidence alone.

### B2. `DEPENDENCY_DRIFT` must be about *this* dependency (#57) (P1)

Bump any pin, and a rewritten expectation is held at warn. The credit is
policy, and policy is purchasable.

**Design:** require plausible relatedness — the distribution name whose pin
changed must correspond to a module the test file imports, directly or through
the package under test. A `requests` bump credits expectation changes in tests
that import `requests`; it credits nothing in a test about invoice arithmetic.

- **Residual:** still buyable by bumping a dependency the test genuinely uses.
  Stated, not hidden — the cost rises from "any manifest edit" to "a manifest
  edit for a dependency this test actually touches".
- **How this gets falsified:** the corpus commits that legitimately earn
  `DEPENDENCY_DRIFT` today (starlette `5ccbc62175`, `100f05a66b`, flask's two
  werkzeug bumps) must keep earning it. If any loses the credit and blocks,
  the relatedness test is too strict.

### B3. `PROD_SYMBOL_REMOVED` (D8) (P2)

Same shape, same fix: the removed symbol should be related to the deleted test,
not merely present somewhere in the diff.

---

## Group D: outside the tool

`#1` (change production until the old test passes) and `#3` (never run
greenwash) are not tool problems and no design here addresses them. They belong
in `docs/stability.md` and the README as deployment guidance: greenwash as a
**required CI check** with base-side configuration, not as an agent stop-hook
alone; and mutation testing or property tests as the answer to `#1`. The report
is right that `#1` always needs a human.

---

## Priority, and where it differs from the report

| | item | report | here | why |
|---|---|---|---|---|
| P0 | C1 runner enumeration + opaque denial | P2 | **P0** | measured: four complete passes, not missed findings |
| P0 | C2 dialect tokens | P2 | **P0** | same round as C1, near-zero cost |
| P0 | A1 expectation definition | P0 | P0 | agreed; highest FP risk in the document |
| P0 | A2 subject laundering + hand-off | P0 | P0 | agreed; the hand-off fix is one line |
| P1 | C3 guard semantics | P1 | P1 | agreed |
| P1 | C4 collection control | P2 | **P1** | an entire file leaves collection silently |
| P1 | B1 opaque per-relationship | P1 | P1 | agreed, but cannot be validated on this corpus |
| P1 | B2 dependency relatedness | — | P1 | the cheapest way to make a bought credit cost something |
| P1 | A3 unittest parity | P3 | **P1** | cheap, and the corpus has zero power to catch the gap |
| P2 | A4 subject-less | P3 | P2 | blast radius is bigger than the fix |
| P2 | A5 helper expansion | — | P2 | partial by nature |

## The rule this document is written under

Every section above is a hypothesis about greenwash's behaviour. This project's
own history — recall measured at 0/12 on the first run, an httpx fix predicted
from source that moved zero commits, a release rule that closed a reduction and
not the bug it was reduced from — says such hypotheses are wrong often enough
that shipping one unmeasured is the actual risk.

So: fixtures red before the fix, the attack re-run after **every** change, the
corpus sweep before any number is written down, the decoy arms replayed, and
any design whose validation plan says "the corpus cannot show this" ships with
that sentence attached to it in public.
