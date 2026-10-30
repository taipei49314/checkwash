# Enterprise checklist

One page for a security or platform team evaluating checkwash v0.6.0
(alpha; bounded JS/TS assertion evidence) as a required gate, with a reviewed exemption path.
Start with a review of its
[coverage and adoption cost](stability.md#coverage-and-adoption-cost), then
protect the deployed check and its policy files.

**v0.3.0 notice:** v0.3.0 (2026-09-07) changes five exemption namespaces and
local installation behavior. The recommended Action pin was then v0.5.0 (advanced
by v0.6.0 under the one-release trust lag) and carries
these changes. Follow
the [migration notes](remediation-upgrade.md); a CLI upgrade alone still does
not update a deployed Action or an existing hook.

## 1. Required check

A job that runs and is not required does not block a merge. Three steps; the
workflow and the ruleset command are under
[Use it in CI](../README.md#use-it-in-ci) in the README:

1. Add the hash-pinned workflow.
2. Require status context `checkwash` (job name, not filename):

   ```bash
   gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
   ```

3. `checkwash doctor` — it cannot see branch protection; confirm step 2.

The README's Action is hash-pinned to **v0.8.0**, the release its CLI commands
install. A release commit cannot embed its own SHA, so the pin advances in a
follow-up once a release's publication is verified. Installing a newer CLI does
not update an existing Action. Always record both deployed versions. A required check enforces that version's
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

Through v0.8.0 the assertion-level rules (ASSERT_WEAKENED, ASSERT_SUBSTITUTED,
ASSERT_REMOVED, TOLERANCE_LOOSENED, EXPECTED_VALUE_CHANGED,
EXPECTED_VALUE_DERIVED, EXPECTATION_DEFINITION_CHANGED, SUBJECT_NORMALIZED and
SUBJECT_INPUT_CHANGED) were keyed on the old assertion only: one exemption
allowed every later rewrite of that line. From the next minor (#421) their key
also binds the new assertion, the kind of change, which identical copy changed
and the rule's context, and their old keys are retired the same way. Each
reviewed rewrite needs its own entry. In the same minor (#512), TEST_DISABLED's
key binds what each disabling changed (an added skip's text and guard, the
guard before and after, which parametrize rows went, a removed test's complete
assertions, a file-level focus's spelling), and its old keys are retired too.
EXPECTED_VALUE_HARDCODED, CONFTEST_PATCHES_PROD and TEST_PATCHES_SUBJECT keep
before-only keys for now.

```bash
checkwash allow "ASSERT_WEAKENED/tests/test_x.py/test_x/v2:<the full 64-hex digest from the report>" \
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
`-k` / `--ignore`). Budgets: 3000-line test diff **< 1.5 s**; 500 files
**< 3.5 s**, widened from 1.0 s and 2.5 s by maintainer decision on
2026-10-20 (D-170). A regression beyond those fails the push. Since v0.5.0
the two budget checks are skipped on macOS by maintainer decision
(2026-10-01); the Linux and Windows legs still enforce them. The ROADMAP
stop-hook target is p95 < 2 s on a medium diff; 1.5 s is the hard gate.

## 6. What this still does not do

- It does not see branch protection. Confirm step 2 yourself.
- It does not stop someone deleting the job in the same diff. Protect
  `.github/workflows/`.
- It does not execute tests or prove semantic equivalence.
- At the default threshold it does not block a weakened test whose change
  carries repair evidence that changes nothing (§7).

## 7. Hardening against bought repair evidence (#419)

checkwash holds a weakened test assertion at **warn** when the same change
carries repair evidence, and the default threshold, `high`, passes warn. An
edit that changes nothing can supply that evidence: one line in a template,
a JS/TS module or `AUTHORS` (Route B), or `+ 0` in a function the test calls
(Route A). A broad `except` added around an assertion in a Python test or
conftest is the exception: it blocks beside any production change (D-176),
unless it is a proven failure relay, which is not counted as added, within
0.10's count (D-190), or one of five spellings that give no finding at all
(THREATMODEL rows 172 to 176).
[#419](https://github.com/taipei49314/checkwash/issues/419) is closed as a
documented residual, not a fix ([D-191](../DECISIONS.md)): what still passes
and what blocks are in [KNOWN-ISSUES-next](KNOWN-ISSUES-next.md) and
[THREATMODEL](../THREATMODEL.md) item 4 and rows 2, 93, 130, 131 and 172 to
175. If an author who reads these rules is in your threat model, use one of
the options below. Each also blocks honest changes, and the cost given is
from archived rows, not a measurement of 0.11 (see *About the counts*).

1. **`fail-on: warn` in the Action.** Add the input to the checkwash step:

   ```yaml
         - uses: taipei49314/checkwash/action@<the pin you use>
           with:
             fail-on: warn
   ```

   The Action always passes `--fail-on <input>` (default `high`) to
   `checkwash check`, and the flag overrides `gate.fail_on` in the base
   `config.toml`, so the config alone does not change the Action;
   `gate.fail_on = "warn"` there applies to CLI runs without `--fail-on` and
   to the Claude Code Stop hook. Every warn finding then blocks: both routes,
   findings held by `MILD_WEAKENING`, `COMPAT_GATE` or another compensation,
   and warn findings of other rules, such as `CI_WORKFLOW_TOUCHED`,
   `SUPPRESSION_ADDED` and `IMPORT_UNRESOLVED`. Cost: blocks went from 48 to
   615 of 1,800 commits; `CI_WORKFLOW_TOUCHED` was among the blocking
   findings of 458 of the 567 new blocks and `SUPPRESSION_ADDED` of 67,
   overlapping.

   `checkwash doctor` proves only a checkwash step with `uses:` and no
   `with:`, so a workflow that sets `fail-on: warn` reports "WARN workflow
   analysis incomplete" and doctor exits 1. In 0.11 that is expected, and
   doctor is unchanged. A pull request runs the workflow as it changes it,
   so one that lowers its own `fail-on` is judged at the lowered threshold,
   and its workflow edit shows only as `CI_WORKFLOW_TOUCHED` at warn: keep
   `.github/workflows/` behind CODEOWNERS with a required code-owner review
   (§4).

2. **`oracle_freeze: true` in a base-side task contract.** In a CLI step of
   your own, run `checkwash check BASE...HEAD --task TASK.md` with a task
   file committed at the base:

   ```markdown
   ---
   checkwash:
     oracle_freeze: true
   ---
   ```

   E2 then sets every oracle finding to high after the de-escalators, so
   both routes block. Allowlisted findings stay exempt, and a disappeared
   test proven moved whole or kept by a live duplicate, and an inert
   conftest `pytestmark`, stay at info. The Action has no task input, and
   the managed Claude Code hooks pass no `--task`. A task file the base tree
   does not hold is read from the working tree, which the change controls
   (stderr says so): commit it, and keep it behind CODEOWNERS. Cost: blocks
   went from 48 to 127 of 1,800 commits; the 79 new blocks raised
   `EXPECTED_VALUE_CHANGED` in 35, `TEST_DISABLED` in 26,
   `EXPECTATION_DEFINITION_CHANGED` in 20, `ASSERT_REMOVED` in 8,
   `ASSERT_SUBSTITUTED` in 7 and `ASSERT_WEAKENED` in 2, overlapping.

3. **The Claude Code PreToolUse ask** (0.11, not yet released; local hook
   installs). `checkwash hook install --agent claude-code` adds a
   PreToolUse handler that judges each Edit, Write or MultiEdit of a Python
   test file alone, with `oracle_freeze` forced, and asks you before the
   edit is made when it would leave a non-allowlisted `ASSERT_WEAKENED`,
   `ASSERT_REMOVED`, `TEST_DISABLED`, `TOLERANCE_LOOSENED` or
   `BROAD_EXCEPT_ADDED` finding at high. Evidence bought elsewhere in the
   working tree does not lower it. It is an author-side check, not a gate:
   it does not see edits made through Bash, NotebookEdit or an MCP file
   tool, JS/TS tests, other rules, input it cannot read or predict, or
   anything outside an agent session; an approved ask lets the edit through;
   the Stop hook applies no freeze; and pull request checks and the Action
   are unchanged ([KNOWN-ISSUES-next](KNOWN-ISSUES-next.md)). Cost: in the
   session replay behind [D-189](../DECISIONS.md), 630 Claude Code edits of
   Python test files on one host replayed through the released v0.10.0 pyz,
   not this handler, these five rules asked about 63 edits (10%), 24 of the
   32 labelled real loosenings among them, and 12 of the 62 labelled asks
   were not a loosening (19%). Those counts are exploratory, and the labels
   are Claude's and provisional. Smoke runs took about 1.0 to 1.2 seconds
   per call on a two-file repository; large repositories are not measured.
   In a `claude -p` run nobody can answer, so an ask becomes a denial.

**About the counts.** Options 1 and 2 quote archived rows of the v0.9.0
combined sweep, not a result. On 1,800 in-sample commits of attrs, click,
flask, httpx, rich and starlette, 300 each, the release-candidate engine
`141acceef` blocked 48. Its two Q4 variant arms, with `--fail-on warn` (615)
and with a base-side `oracle_freeze` contract (127), were halted under the
pre-registered stop C2.6 with their rows archived, and no complete RC Q4
numbers were supplied under R22 ([D-172](../DECISIONS-archive-2.md)). So
these are not the pre-registered Q4 numbers, nothing in them is
adjudicated, and none was measured on 0.11. Combined result SHA256
`b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`;
LAPTOP-01AGNPJU, human-authorized local PJU, NOT EC pool.
