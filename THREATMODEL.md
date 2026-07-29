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
disabled tests, (M1:) loosened tolerances, rewritten snapshots, hardcoded
expectations, broad exception swallowing, suppression comments, CI/guardrail
self-relaxation, hallucinated imports, scope drift, hidden Unicode.

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
4. **Non-Python prod files (v0.1).** Triviality analysis of changed prod
   files only works for Python; other changed prod files conservatively count
   as "non-trivial change present", which *suppresses* the E1 escalation.
   An agent could exploit this by touching a non-Python prod file. Fixed when
   the JS/TS frontend lands (M1/v0.2).

## Known bypasses (public list — contributions welcome)

Maintained here on purpose: every bypass reported becomes a regression
fixture. See CONTRIBUTING ("Send us a cheat") once published.

| # | Bypass | Status |
|---|---|---|
| 1 | Rewrite prod logic so the weak test passes honestly | Out of scope (documented limit) |
| 2 | Touch a non-Python prod file to defuse E1 | Open until JS/TS frontend (M1) |
| 3 | Remove the hook / run outside greenwash | Out of scope; use CI required checks |
