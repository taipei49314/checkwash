# Enterprise checklist

One page for a security or platform team evaluating checkwash v0.3.3
(alpha; bounded shared-fixture precision fix on v0.3.0) as a required gate, with a reviewed exemption path.
Start with a review of its
[coverage and adoption cost](stability.md#coverage-and-adoption-cost), then
protect the deployed check and its policy files.

**v0.3.0 notice:** v0.3.0 (2026-09-07) changes five exemption namespaces and
local installation behavior. The recommended Action pin is v0.3.2 (advanced
by v0.3.3 under the one-release trust lag; the v0.3.0 engine) and carries
these changes. Follow
the [migration notes](remediation-upgrade.md); a CLI upgrade alone still does
not update a deployed Action or an existing hook.

## 1. Required check

A job that runs and is not required does not block a merge. Three steps in
the [README](../README.md):

1. Add the hash-pinned workflow.
2. Require status context `checkwash` (job name, not filename):

   ```bash
   gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
   ```

3. `checkwash doctor` — it cannot see branch protection; confirm step 2.

The README's Action is hash-pinned to **v0.3.2** under the one-release
trust-lag policy. Installing the v0.3.3 CLI does not update that Action;
the shared-fixture precision fix is only in the newer CLI. Always
record both deployed versions. A required check enforces that version's
configured verdict, not a guarantee that the change is correct.

Optional PR line comments (T2.2): set `comment-pr: true` and add
`pull-requests: write`. The engine does not talk to the network; the
Action posts a review and soft-fails if the token cannot write.

## 2. SARIF (optional)

```bash
checkwash check BASE...HEAD --format sarif > checkwash.sarif
```

SARIF 2.1.0 for GitHub code scanning. It is a projection of findings, not a
second verdict. Exit codes stay 0 / 1 / 2. Use the three-dot range so the
diff is the PR, not the last commit. A wash split across merged PRs is
still outside that window — [process-windows.md](process-windows.md).

## 3. Allowlist — reviewed, time-boxed, base-side

Up to v0.2.13, GUARDRAIL_TOUCHED, CI_WORKFLOW_TOUCHED,
TEST_FILE_UNPARSEABLE, SCOPE_DRIFT and SNAPSHOT_CODE_COCHANGE used rule/path
identities: a per-fingerprint exemption is file-wide for these rules and may
cover later unrelated content. Since v0.3.0 the key binds both snapshots and
the rule's context, rejects old keys, and requires a newly reviewed v2 approval.
The expiry limits below do not narrow an old key's scope. Do not mechanically
rewrite the digest or use a ledger entry to approve its own cleanup.

```bash
checkwash allow "ASSERT_WEAKENED/tests/test_x.py/test_x/abcd1234ef56" \
  --reason "literal tracks a documented API rename in #1234"
# then commit the ledger path printed by the command
```

- Both `.checkwash/allow.toml` and `.greenwash/allow.toml` are supported.
  An existing file is selected in that order; otherwise the writer uses an
  existing configuration directory (`.checkwash/` first), or `.greenwash/`
  when neither exists. Reads from the base use the same per-file precedence.
- `--reason` is required and cannot be empty.
- Default expiry is 90 days; the hard cap is **180 days** on write *and*
  on read. A hand-edited ten-year window is ignored.
- The ledger is read from the **base** of the diff. An agent cannot exempt
  the change under review. The entry applies to the *next* diff after it
  lands.
- `checkwash doctor` reports how many entries are active, expired, or
  over the cap. The term report footer prints `allow_cap=180d`.

## 4. CODEOWNERS

Put the ledger and the gate behind people who can say no:

```
# .github/CODEOWNERS
.greenwash/              @org/security-reviewers
.checkwash/              @org/security-reviewers
.github/workflows/       @org/security-reviewers
action/required-ruleset.json @org/security-reviewers
```

A CODEOWNERS file is not a merge gate unless the branch rule also requires
a code-owner review. Protect both supported configuration directories even
if the repository currently uses only one.

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
