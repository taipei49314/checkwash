# Defence design against the 2026-08-11 red-team report

> **Status: proposed. Nothing in this document is implemented.**
> Every section states what would have to be *measured* before it ships. A
> design that has not been run against the corpus and the decoy arms is a
> hypothesis, and this project has a long record of hypotheses about its own
> behaviour being overturned by the first measurement. Read the "How this gets
> falsified" line in each section as the real content.

Source: an informed-adversary red-team report against v0.1.15, supplied by the
maintainer (not vendored here — that is the author's call to make). Eight of
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

### A5. Oracles behind custom helpers (P2, partial by nature)

`assert_invoice_ok(total)` in `helpers.py`, then the test stops calling it or
calls it with a constant. The frontend understands bare `assert`, curated
unittest methods and some `pytest.raises`; it does not understand hamcrest, a
hand-written `check_eq`, or an assert inside a fixture.

**Design, bounded and honest:** in-file wrapper expansion only. A function
defined in a *test-role* file whose body is only assertions, called from a
collected unit, contributes its assertions to that unit at the call site, to a
depth of one. Cross-file and third-party matchers stay out of scope and stay
documented as out of scope.

- **Residual:** the interesting half. Once the helper lives in another module,
  greenwash is blind again.
- **How this gets falsified:** the helper shape must block; sweep for units
  whose assertion count jumps, which is where the FPs would be.

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
