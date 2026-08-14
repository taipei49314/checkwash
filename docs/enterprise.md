# Enterprise checklist

One page for a security or platform team that wants greenwash as a required
gate, with a reviewed exemption path.

## 1. Required check

A job that runs and is not required does not block a merge. Three steps in
the [README](../README.md):

1. Add the hash-pinned workflow.
2. Require status context `greenwash` (job name, not filename):

   ```bash
   gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
   ```

3. `greenwash doctor` — it cannot see branch protection; confirm step 2.

Optional PR line comments (T2.2): set `comment-pr: true` and add
`pull-requests: write`. The engine does not talk to the network; the
Action posts a review and soft-fails if the token cannot write.

## 2. SARIF (optional)

```bash
greenwash check BASE...HEAD --format sarif > greenwash.sarif
```

SARIF 2.1.0 for GitHub code scanning. It is a projection of findings, not a
second verdict. Exit codes stay 0 / 1 / 2. Use the three-dot range so the
diff is the PR, not the last commit. A wash split across merged PRs is
still outside that window — [process-windows.md](process-windows.md).

## 3. Allowlist — reviewed, time-boxed, base-side

```bash
greenwash allow "ASSERT_WEAKENED/tests/test_x.py/test_x/abcd1234ef56" \
  --reason "literal tracks a documented API rename in #1234"
# then commit .greenwash/allow.toml
```

- `--reason` is required and cannot be empty.
- Default expiry is 90 days; the hard cap is **180 days** on write *and*
  on read. A hand-edited ten-year window is ignored.
- The ledger is read from the **base** of the diff. An agent cannot exempt
  the change under review. The entry applies to the *next* diff after it
  lands.
- `greenwash doctor` reports how many entries are active, expired, or
  over the cap. The term report footer prints `allow_cap=180d`.

## 4. CODEOWNERS

Put the ledger and the gate behind people who can say no:

```
# .github/CODEOWNERS
.greenwash/              @org/security-reviewers
.github/workflows/       @org/security-reviewers
action/required-ruleset.json @org/security-reviewers
```

A CODEOWNERS file is not a merge gate unless the branch rule also requires
a code-owner review.

## 5. Perf SLO

`tests/gates/test_perf.py` runs in default `pytest` (the CI job has no
`-k` / `--ignore`). Budgets: 3000-line test diff **< 1.0 s**; 500 files
**< 2.5 s**. A regression beyond those fails the push. The ROADMAP
stop-hook target is p95 < 2 s on a medium diff; 1.0 s is the hard gate.

## 6. What this still does not do

- It does not see branch protection. Confirm step 2 yourself.
- It does not stop someone deleting the job in the same diff. Protect
  `.github/workflows/`.
- It does not execute tests or prove semantic equivalence.
