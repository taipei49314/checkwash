# Threat model

greenwash is a **deterministic tripwire that raises the cost of cheating**.
It is not a guarantee, and it never claims "no cheating" — report wording is
fixed at "no known tampering pattern detected".

## Attacker model

The head side of the diff — including the entire working tree in hook mode —
is attacker-controlled. The attacker is a coding agent (or a human) trying to
make CI green without doing the requested work.

## What greenwash catches (v0.1)

Oracle-layer attacks visible in the diff: deleted/weakened assertions,
self-comparisons that can never fail, tests disabled by any of the pytest
idioms (function/class/module markers, `self.skipTest`, conftest collection
hooks), tests removed from collection by renaming the file or the class,
assertions parked behind an early `return`, deleted parametrize rows.
(M1:) loosened tolerances, rewritten snapshots, hardcoded expectations, broad
exception swallowing, suppression comments, CI/guardrail self-relaxation,
hallucinated imports, scope drift, hidden Unicode.

## What greenwash cannot catch — known and accepted

1. **Honest-looking dishonesty.** An agent that rewrites production logic so
   a bad test passes "honestly" is, at the diff layer, in principle
   undecidable. This is the fundamental limit of the approach.
2. **Out-of-band tampering.** An agent with shell access can edit
   `.git/greenwash/` state, remove the hook, or bypass the CLI entirely.
   Pair with CI-side checks (base-side config, required checks) for that.
3. **Curation gaps.** Custom assertion helpers, hamcrest-style matchers, and
   indirect assertions via fixtures are invisible until curated. Coverage is
   measured and reported, not assumed.
4. **Opaque prod changes (v0.1).** Repair evidence is computed from Python
   ASTs. A changed prod file greenwash cannot analyse — non-Python, deleted,
   or unparseable — counts as evidence and therefore *suppresses* the E1
   escalation. An agent can exploit this by touching one such file. Narrowed
   when the JS/TS frontend lands (M1/v0.2); note that touching an unrelated
   *Python* prod file no longer works.
5. **Indirection beyond one hop.** Repair evidence follows the call graph one
   hop from the test. A change three layers down, with no closer signal, is
   treated as unrelated (fails safe toward flagging, not toward silence).

## Known bypasses (public list — contributions welcome)

Maintained here on purpose: every bypass reported becomes a regression
fixture. See CONTRIBUTING ("Send us a cheat") once published.

| # | Bypass | Status |
|---|---|---|
| 1 | Rewrite prod logic so the weak test passes honestly | Out of scope (documented limit) |
| 2 | Touch a non-Python / unparseable prod file to defuse E1 | Open until JS/TS frontend (M1) |
| 3 | Remove the hook / run outside greenwash | Out of scope; use CI required checks |
| 4 | Add a dead constant, reorder defs, or edit an unrelated function to defuse E1 | **Closed** — evidence is symbol-relevant, not diff-global |
| 5 | `git mv` / plain `mv` a test file out of collection | **Closed** in both range and worktree mode |
| 6 | Rename the test class out of pytest's `Test*` rule | **Closed** |
| 7 | conftest hook that skips the whole suite | **Closed** (curated control list) |
| 8 | Early `return`, deleted parametrize rows | **Closed** |
| 9 | Sacrificial `@pytest.mark.skip` test absorbing deleted assertions via D2 | **Closed** — disabled units are not "live" |
| 10 | `assert f(x) == f(x)` self-comparison | **Closed** (TAUTOLOGY) |
| 11 | Pass `BASE...HEAD` so base-branch commits defuse E1 | **Closed** (merge-base resolved) |

Bypasses 4–11 were found by adversarial review and each has a regression
fixture. Report a new one and it becomes the next row.
