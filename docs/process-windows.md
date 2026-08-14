# Process windows: what a single-diff tool cannot see

greenwash judges one range. A cheat split across two pull requests is
outside that range, and no detector in this repository can close that
gap. The roadmap names this **L0-C** (docs/ROADMAP-top-tier.md,
docs/redteam-residual-after-p0.md): multi-commit / multi-PR laundering
is a process limit, not an open row waiting for a rule.

This page is the process answer. It does not claim the engine now
covers L0-C.

## What a single range sees

| invocation | window |
|---|---|
| `greenwash check` | `HEAD` vs the working tree |
| `greenwash check HEAD~1..HEAD` | one commit |
| `greenwash check origin/main...HEAD` | the pull request: merge-base to HEAD |
| `greenwash sweep HEAD --limit 300` | 300 consecutive non-merge commits |

`check BASE...HEAD` (three dots) is the PR shape. Two dots
(`BASE..HEAD`) pull in base-branch commits the PR did not introduce.
`doctor` already says this.

A reviewer who only runs `HEAD~1..HEAD` on the last commit of a
stacked change will miss a wash that landed earlier in the same
branch. The merge-base range is the smallest window that is still a
PR.

## What a wash looks like

Two honest-looking diffs, one cheat:

1. PR A adds an unused helper, a skip marker, or a second copy of a
   test. Reviewers merge it because nothing got weaker.
2. PR B "cleans up": deletes the original assertion, or rewrites the
   expectation to match the bug. Against PR B's own range the deletion
   has a surviving copy, or the rewrite has a helper that was "always
   there".

Each range is a pass. The union is a missing oracle. That is L0-C.

The same shape exists inside one PR if the gate only diffs the tip
commit. `BASE...HEAD` closes *that* hole. It does not close a wash
that already merged.

## What to run

**On every pull request** (CI, required check):

```bash
greenwash check origin/main...HEAD
```

The Action already checks out with `fetch-depth: 0` so the merge base
exists. Do not gate the job on the last commit only.

**On a long-lived branch or a stack**, treat the stack as one window:

```bash
greenwash check $(git merge-base origin/main HEAD)...HEAD
```

**On a repository's history**, after a merge or as a periodic check:

```bash
greenwash sweep HEAD --limit 300 --repo .
```

`sweep` is measurement, not a merge gate. It reports how often the
engine would have blocked, including the commits a per-PR gate would
have seen twice (the PR, then the merge). It does not invent a
cross-PR identity for a helper introduced last month.

**Optional integration:** run `sweep` on the PR branch's unique
commits as an advisory job, next to the required `check`. That
surfaces a tip-only wash inside the branch. It still cannot see a
wash whose first half already landed on `main`.

## What this does not do

- It does not close L0-C in the engine. A determined split across
  merged PRs remains a pass on each half.
- It does not recommend widening `check` to "the last N merges" as a
  default. That re-reports findings the project already accepted, and
  the allowlist is per-fingerprint on the base side — not a history
  memory.
- It does not replace review of stacked PRs. Reviewers who can see
  both halves are the actual control.

The tripwire raises the cost of cheating *inside the window you give
it*. Choosing the window is an operational decision; publishing a
detector that pretends to choose it would be a claim this project
cannot support.
