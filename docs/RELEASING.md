# Releasing

The remediation candidate of D-055 shipped as v0.3.0 on 2026-09-07 — the
minor release its fingerprint and machine-interface break required
([upgrade notes](remediation-upgrade.md)). The promotion of the verified
fixed Action SHA under the one-release trust lag was a separate, later step:
v0.3.1 (2026-09-07) advanced the recommended pin to v0.3.0 (D-057) and v0.3.2
advanced it to v0.3.1 (D-058). The exact ledger-cleanup review is still a
separate governance change (D-055).

The order matters, and it is the whole answer to a question that has now been
asked twice: *the tag-parity gate fails before I cut the tag — isn't that
circular?*

It is not. It is an ordering constraint, and this is the order.

```bash
# 1. bump, in both places
#    src/checkwash/__init__.py  __version__ = "0.1.14"
#    pyproject.toml             version = "0.1.14"

# 2. update the pins the version owns
#    README.md: every @vX.Y.Z and `rev: vX.Y.Z`
#    STATE.md:  the version row of the authoritative table

# 3. commit, on a release branch (release/v0.1.14)
git add -A && git commit

# 4. TAG — before anything verifies, and before anything is pushed
git tag -a v0.1.14 -m "..."

# 5. verify. Everything is green here or the release does not happen.
pytest                                  # tag parity is now checkable, and checked
checkwash check --repo .                # the judge judges itself

# 5a. main first, without the tag. The release commit reaches main through
#     its PR; the tag of step 4 stays local. Before merging, step 5 has run on
#     the PR's final head (if the branch was updated with main, move the local
#     tag to the new head and repeat step 5), and that head's pull_request
#     `verdict gate` run concluded success: the first (newest) line ends in
#     "completed success".
git push origin release/v0.1.14         # open the PR
gh run list --workflow verdict-gate.yml --event pull_request --commit <head-sha> \
  --json databaseId,attempt,headSha,status,conclusion -q '.[] | "\(.databaseId) \(.attempt) \(.headSha) \(.status) \(.conclusion)"'
#     merge it. A GitHub merge (merge, squash or rebase) always makes a new
#     commit; that commit is the release commit, and the local tag moves onto it.
gh pr view <pr> --json mergeCommit -q .mergeCommit.oid      # <release-commit>
git fetch origin
test "$(git rev-parse '<release-commit>^{tree}')" = "$(git rev-parse '<head-sha>^{tree}')"
git tag -f -a v0.1.14 -m "..." <release-commit>

# 5b. the release commit's main-push `verdict gate` run concluded success:
#     exactly one line, ending in "completed success". Re-query an empty
#     answer before treating the run as missing.
gh run list --workflow verdict-gate.yml --event push --branch main --commit <release-commit> \
  --json databaseId,attempt,headSha,status,conclusion -q '.[] | "\(.databaseId) \(.attempt) \(.headSha) \(.status) \(.conclusion)"'
#     baseline.toml there pins the previous release: its tag is the highest
#     other vX.Y.Z tag merged into the release commit (the tag-push run's rule),
#     and its commit is that tag's commit. The two lines must agree.
git show <release-commit>:tests/verdict_gate/baseline.toml | python -c "import sys, tomllib; b = tomllib.load(sys.stdin.buffer)['baseline']; print(b['tag'], b['commit'])"
t=$(git tag --merged <release-commit> --list 'v*' --sort=-v:refname | grep -Ex 'v[0-9]+\.[0-9]+\.[0-9]+' | grep -vx v0.1.14 | head -1); echo "$t $(git rev-parse "$t^{commit}")"
#     the local tag is on the release commit, and the release commit is on main
test "$(git rev-parse 'v0.1.14^{commit}')" = <release-commit>
git merge-base --is-ancestor <release-commit> origin/main

# 6. unlock the tag ruleset for this push only (it rejects v* creation,
#    update and deletion at every other moment; see "The release slot")
printf '{"enforcement":"disabled"}' | gh api repos/taipei49314/checkwash/rulesets/22162219 --method PUT --input -

# 7. push the tag, alone: main is already there (step 5a)
git push origin v0.1.14

# 8. lock it again, immediately, before the GitHub Release is cut
printf '{"enforcement":"active"}' | gh api repos/taipei49314/checkwash/rulesets/22162219 --method PUT --input -

# 8a. the tag-push `verdict gate` run concluded success, on the same commit:
#     exactly one line, ending in "completed success"
gh run list --workflow verdict-gate.yml --event push --branch v0.1.14 --commit <release-commit> \
  --json databaseId,attempt,headSha,status,conclusion -q '.[] | "\(.databaseId) \(.attempt) \(.headSha) \(.status) \(.conclusion)"'

# 8b. only now publish the GitHub Release (the release workflow builds,
#     qualifies and publishes from it); the grant record cites both runs,
#     id and attempt

# 8c. after publishing: the rotation PR repoints the verdict gate's pins
```

## Main first, then the tag

Steps 5a to 8c exist for the previous-release verdict gate (#201:
`tools/verdict_gate.py`, run by `.github/workflows/verdict-gate.yml`). It runs
the previous release's `checkwash.pyz` and the candidate through the CLI on the
same cases and fails when a block turns into a pass that the maintainer has not
accepted. The release workflow runs only after the tag exists, so the gate
works through workflow runs on the exact release commit. Step 7 used to push
`main` and the tag together, which left no green `main` run to check before the
tag was on the remote. (v0.5.0 in practice reached `main` through #193 before
its release run.)

- **Before the release PR merges (5a).** Step 5 has run on the PR's final
  head. When `main` moved, the branch ruleset's strict status-check policy
  makes the branch be updated before it can merge; the update is a new commit
  with a new tree, so the local tag moves to the new head and step 5 runs
  again. That head's `pull_request` run of `verdict gate` concluded `success`.
  The gate is advisory on other PRs (#201 Decision 3); on a release PR this
  run is required, because it is the last check before `main` carries the
  bump. A GitHub merge always makes a new commit (v0.5.0 is tagged on
  `24b60a2`, the merge commit of #193), so the local tag always moves onto it.
  Because the PR is up to date when it merges, that commit's tree is the final
  head's tree, and the `test` in 5a checks it.
- **Before the tag is pushed (5b).** The release commit is on `main`, its
  `verdict gate` run on the push to `main` is `completed` with conclusion
  `success`, `[baseline]` in `tests/verdict_gate/baseline.toml` pins the tag
  and commit that the tag-push run will require, and the local tag is on the
  release commit. A failed, cancelled or missing run stops the release here.
  `main` then carries a bumped version and README and STATE pins for a tag that
  is not cut, so tag parity stays red: the receipt goes to the maintainer, a
  revert PR of the release PR puts `main` back, and the release starts again
  at step 1 once the cause is fixed. Between the merge and step 7, the tag
  parity test in `ci.yml` is red on `main` in any case: the version is bumped
  and the tag is not on the remote yet. That is the gate working (see below).
  The verdict gate does not need the tag on a `main` run.
- **Before the GitHub Release is published (8a).** The run on the tag push,
  same commit, concluded `success`. On a tag push the gate also fails unless
  HEAD is the pushed tag's commit and the baseline is the highest other `v*`
  tag merged into HEAD, which is why the pins move only after publication. If
  this run fails, the Release is not published, so nothing reaches PyPI. The
  tag stays public (the tag ruleset rejects deletion too), and `main`'s README
  already advertises `pipx … @vX.Y.Z` and `rev: vX.Y.Z`, so git installs get
  that commit. The receipt goes to the maintainer, who decides between a revert
  PR of the release PR on `main` and a fixed patch release.
- **The grant record (8b).** The release's one-time authorization in this file
  cites both runs, id and attempt (a re-run keeps its id): the `main` run of 5b
  and the tag run of 8a. The authorization is written before the release, so
  the post-publication docs PR, the one that records the publication (as #194
  did for v0.5.0), adds them to it.
- **After publishing (8c): the rotation PR.** One reviewed PR repoints the
  verdict gate at the release just published:
  - `[baseline]` in `tests/verdict_gate/baseline.toml`: tag, version and
    commit of the new release, and the sha256 and size of its `checkwash.pyz`
    from `gh release view vX.Y.Z --json assets` (the gate re-checks both on
    every run);
  - `baseline_blocked`: re-pinned from the value the rotation PR's run
    proposes;
  - `[t3.cases]`: re-read from the gate's proposal, since T3 comes from the new
    tag's `tests/data/javascript_chai_mutations.json`;
  - `[canary]`: not rotated with the baseline. Its v0.4.2 → v0.5.0 pair and,
    once pinned, its `block_to_pass` set stay unless a reviewed PR re-pins
    them;
  - the acceptance file, `tests/gates/verdict_gate_accepted.toml`: its
    `baseline`, and the removal of every stale entry the rotation PR's run
    names (the gate fails on a stale entry). That file and `DECISIONS.md` are
    maintainer-only (#201 Decision 1, `AGENTS.md`), so the maintainer commits
    both changes to the rotation PR with a `DECISIONS.md` entry, and the PR
    stays red until then.

  The rotation PR's run names every acceptance entry that went stale (the case
  no longer needs one: the new baseline already passes it and its label is not
  `block`; `known-regression` entries stay, held by the label anchor) and every
  added, dropped or re-hashed `chai:` case.

## The release slot

The weekly automatic slot introduced by estate T-57 was canceled by T-197.
Since 2026-09-26 the estate no longer governs this repository (estate POLICY
`independent-repos`, T-451): it neither claims, authorizes nor releases
checkwash. Each bump, tag, release or downstream re-pin needs its own explicit
one-time maintainer authorization, recorded in this file.
T-229's v0.3.3 grant is consumed. T-332 authorized v0.3.4 once, with
source-bound remote temporary-tag qualification, exact-source integration,
publication and identity verification followed by refreezing. Its
[release record](releases/v0.3.4-public-launch.md) preserves the separate
T-255 frozen comparison and qualification residuals; it does not waive the
full release tests, tag identity, nine-platform comparison or package checks.
There is no automatic next slot. Outside an explicitly authorized release,
nothing is bumped, tagged or released, and the tag ruleset
`release tags: cut only at the release slot` (id 22162219, empty bypass list)
rejects any `v*` tag creation, update or deletion with `GH013` — for everyone,
owner included. Steps 6 and 8 above are the only sanctioned way through it;
both commands are recorded with that release's authorization in this file,
together with the id and attempt of the `verdict gate` run that cleared the
tag push (step 5b) and of the run on the pushed tag that cleared publication
(step 8a).
The ruleset cannot tell an agent holding the owner's token from the owner, so
it does not stop a deliberate actor; it turns tagging from a one-liner into a
visible three-step.

T-436 recorded the human-authorized v0.4.0 issue-resolution release and is
**consumed**: published 2026-09-22 from `6dd3158653c3569279fb2c56cef6af30a959d844`
with publication and identity checks complete
([release](https://github.com/taipei49314/checkwash/releases/tag/v0.4.0),
[candidate record](releases/v0.4.0-public-launch.md)). It granted no
subsequent release; any further bump, tag or release needs a new explicit
human instruction.

On 2026-09-23 the maintainer explicitly authorized merging PR #166 and
publishing v0.4.1. This separate one-time scope covers the Node assertion
repair, its regression prevention, release qualification and publication;
it does not authorize another release. The
[v0.4.1 guide](releases/v0.4.1-public-launch.md) links the publication record.
The tag ruleset is restored immediately after the authorized tag push.

The maintainer subsequently accepted the v0.4.2 release plan with
"好 依你規劃走". Estate T-449 covers the bounded JS/TS foundation release,
its necessary regression repairs, independently selected JS/TS history replay,
fixed Python sweep, final-source remote qualification and one publication.
The [v0.4.2 guide](releases/v0.4.2-public-launch.md) records its limits. All product
workloads run remotely; this scope supplies no work-machine testing exception.
The recommended Action advances only to prior stable v0.4.1. Publication and
artifact verification consume this grant; another version requires a new scope.

On 2026-10-01 the maintainer chose version 0.5.0 for the #172–#182 issue round
and wrote "授權發粄" (authorize the release). This one-time scope covers the
version bump, THREATMODEL rows 104–112 with their pins (text as proposed in the
merged PRs, numbered in issue order, SPEC unchanged), skipping the two
performance budget checks on macOS, one tag `v0.5.0`, the GitHub Release with
its PyPI publication, and the publication checks. The maintainer set the tag
gate in the same conversation: tag only if the fixed 1,800-commit sweep shows
no extra block against the reference arm; otherwise stop and hand the list over.
The pool sweep of `3cef2a5` (estate T-494, run 36888070539) reports the two
extra blocks v0.4.2 already had, so the tag waits for the maintainer's review of
that list. Steps 6 and 8 run only after that review. The maintainer also
authorized the downstream re-pins after publication, checkwash-corpus first and
smallestlie second, each as its own PR merged only after the maintainer reviews
it. The [v0.5.0 guide](releases/v0.5.0-public-launch.md) records the limits. The
recommended Action advances to prior stable v0.4.2. Publication and artifact
verification consume this grant; another version requires a new scope.

On 2026-10-05 the maintainer stopped the next fix round ("與main差距太大了 先發在修":
`main` was too far ahead, so ship first and fix after) and, asked in the agent
session, chose to approve and merge the stacked fix PRs in order and to
release version 0.6.0 ("發 v0.6.0"). This one-time scope covers the merges of
#258, #259, #262, #264 and #265 with their maintainer commits approved, the
version bump, the THREATMODEL statuses that name the release (a maintainer
commit in the release PR, with the DECISIONS entry for its fingerprint
changes), one tag `v0.6.0`, the GitHub Release with its PyPI publication, the
publication checks and the verdict gate's rotation PR (step 8c). It does not
authorize the downstream re-pins of checkwash-corpus and smallestlie; each
needs its own instruction. The [v0.6.0 guide](releases/v0.6.0-public-launch.md)
records the limits. The recommended Action advances to prior stable v0.5.0.
Publication and artifact verification consume this grant; another version
requires a new scope. The verdict gate's runs on the release commit
`8c70efb` concluded success: the `main` push run 37324377879 (attempt 1,
step 5b) and the tag-push run 37337702973 (attempt 1, step 8a). The tag
`v0.6.0` and the GitHub Release were published on 2026-10-05, and the
rotation PR (#270, D-094) merged the same day: the grant is consumed.

What the slot changes in the README, and what already guards it:

- `pipx … @vX.Y.Z` and `rev: vX.Y.Z` must equal the package version —
  `tests/test_packaging.py::test_readme_install_refs_match_version`
- the Action pin is the newest *prior* stable tag (one-release trust lag) —
  `tests/test_packaging.py::test_readme_action_snippet_is_zizmor_blanket`
- the advertised CLI tag contains the current public install surfaces —
  `tests/test_packaging.py::test_pinned_tag_ships_the_current_source`
- STATE.md's authoritative `version` row —
  `tests/test_state_claims.py::test_version_row_matches_package`

Nothing else in this repository states the current version by hand.

## Why the gate does not get an escape hatch

`tests/test_packaging.py::test_pinned_tag_ships_the_current_source` fails when
the advertised tag does not exist. That is deliberate, and it is not a
theoretical preference: **v0.1.0 shipped pointing at a commit two fixes behind
main**, so visitors read the fixed documentation and installed the unfixed
engine. The gate exists because that happened.

A pre-tag escape hatch — "if the tag is missing, check something weaker and
pass" — was added on 2026-08-08 and removed the same day. It reproduces the
failure mode the assertion's own message describes: *bumping the version used
to make this gate return early and pass*. A gate that passes when its subject
is absent is the "green because it did not run" pattern that has bitten this
project in three separate places (the dogfood job that never executed, the
determinism check that varied the wrong axis, a perf gate that never touched
git).

If a candidate branch's CI is red between the bump and the tag, that is the
gate working. Cut the tag.

The verdict gate is held to the same rule. A release waits for a `success`
conclusion on the release PR's final head, then on the exact release commit,
on `main` and then on the tag; a failed, cancelled or missing run stops it. The workflow has no skip input and
no `continue-on-error`, and moving the baseline pin is not a way to turn a run
green: a block that turns into a pass is either fixed or accepted by the
maintainer in the acceptance file, which the gate then checks like everything
else.

## What ships with a release

The `release` workflow builds these on a published release, and refuses to
build if the version and the tag disagree:

- `checkwash-X.Y.Z-py3-none-any.whl` and the sdist — installed into a fresh
  venv in CI, which asserts `pip freeze` contains checkwash and nothing else
- `checkwash.pyz` — the single-file build, gated by `tests/test_zipapp.py`

### Assertion capability qualification

Before uploading release assets or publishing to PyPI, the release workflow
runs `tools/qualify_assertions.py` on the source, the actual built zipapp and
the wheel installed into a fresh venv. All three execute the same owned
assertion support contract in `tests/data/javascript_assertion_support.json`
and the separate `javascript_foundation_mutations.json` supplement through
real Git commits and the CLI. Each loss must report the expected
rule, severity, path, JSON verdict and process exit; preserving controls must
pass without findings. Clean ranges and invalid refs check exits 0 and 2.
These are bounded syntax and mutation checks, not a general false-positive
or adversarial detection-rate estimate.

The deterministic JSON receipts record the suite digest, engine source
commit, source package digest, whether package sources were dirty, artifact
SHA256, reported version and every case result. Qualification checks the
archive's package bytes against the source tree and, for wheels, also checks
the isolated venv's loaded package. A different artifact or loaded package
fails even if its version string matches. The candidate source, commit and
artifact must remain unchanged during the run. No receipt is stored inside
`dist/`, so PyPI receives only its supported distribution files.

The `assertion qualification` workflow also installs the exact SHA recommended
for the Action in the README and runs the same suite. This is explicitly an
**Action-pinned engine** check, not qualification of the composite Action's
wiring. Its receipt names that engine's own source commit and version. It is
a separate job because the one-release trust lag can expose real capability
gaps: the v0.5.0 pin includes the fixes for #172–#181 but lacks the v0.6.0
work on the reports and rulings that followed them. Its actual result is
measured independently. The job
remains visibly failed when cases fail; no expected-failure
or `continue-on-error` waiver turns those gaps green. The recommended pin
and release authorization remain governed by the existing release process.

For local source qualification:

```bash
python tools/qualify_assertions.py --distribution source --output work/assertion-source.json
```

For a built wheel installed into a fresh venv, use the venv's absolute Python
path so neither an editable checkout nor `PYTHONPATH` can supply its engine:

```bash
python tools/qualify_assertions.py --distribution wheel --artifact dist/checkwash-X.Y.Z-py3-none-any.whl --output work/assertion-wheel.json -- /absolute/fresh/bin/python -I -m checkwash
python tools/qualify_assertions.py --distribution pyz --artifact dist/checkwash.pyz --output work/assertion-pyz.json
```

Fixture analysis is zero-network and never executes fixture tests. CI uses
build/install tooling separately to create the candidate distributions.

### pyz reproducibility

The release job builds the zipapp with:

```bash
python -m zipapp src -m "checkwash.zipapp_entry:run" -o dist/checkwash.pyz -c
```

That is **source-reproducible** on the same CPython minor: same `src/`
tree, same `-m` entry, compressed. It is **not** bit-identical across
Python versions or zip implementations. Visitors should treat the
GitHub release asset as the artifact and verify it by running
`python checkwash.pyz --version` and `python checkwash.pyz demo`.
`tests/test_zipapp.py` on every push is the gate that the recipe still
works; the release job is what people download.

Workflow `uses:` are hash-pinned (T2.6). `contents: write` exists only
on the `build` job, only to attach assets to an already-published
release. PyPI uses OIDC (`id-token: write`) and no stored token.

## PyPI

Gated on a repository variable, on purpose — and **the gate is open**:
`PYPI_ENABLED` has been `true` since 2026-09-01, so every GitHub Release
since 0.2.1 has also published to PyPI (`pipx install checkwash`). Cutting a
release *is* publishing to PyPI; there is no separate step, and the wheel and
sdist on PyPI are the same bytes the `build` job attached to the release
(checked on 0.2.11, 2026-09-02). The `pypi` job publishes through trusted
publishing, so no token is stored anywhere by anyone. The three steps that
opened the gate, all the maintainer's:

1. Register checkwash as a trusted publisher on PyPI for this repository and
   the `release` workflow.
2. Set the repository variable `PYPI_ENABLED` to `true`.
3. Keep the `pypi` environment for its deployment protection rules.

Without (2) the job is skipped and releases are GitHub-only. To go back to
GitHub-only releases, unset the variable; nothing else has to change.

**This paragraph used to say something false, and it is worth knowing why.**
It claimed the job was gated behind an environment "that does not exist until
a human creates it". GitHub creates an environment automatically the first
time a job references one, so the gate was open from the moment it was
written. Nobody noticed because the release workflow had never run: it was
added in v0.1.12, whose release predated it. On v0.1.13 it ran for the first
time, published all three assets correctly, and then failed on a trusted
publisher that does not exist — turning a clean release red.

The gate is a repository variable now, because nothing auto-creates one, and
`tests/test_packaging.py::test_pypi_job_is_gated_on_something_that_is_not_auto_created`
fails if it ever goes back to being gated by `environment:` alone. D-032 has
the full account.

## Check the public package page

The package description comes from `README.md` at build time. Use absolute
GitHub URLs for repository files in that README: PyPI cannot resolve paths
such as `docs/stability.md` against the source tree. Inspect the rendered
description as well as the Markdown source, including content inside HTML
disclosures that another renderer may flatten.

Before publishing, check the candidate wheel's name, version, Python
requirement, license, project URLs and embedded description. Confirm the
description matches the intended README and all document links resolve.
Keep alpha status, measurement provenance, refactor cost and Action version
differences visible. This check does not establish detector coverage.

After publishing, check both the unversioned PyPI project page and the exact
version page. Confirm the displayed version, description and links; download
the wheel and sdist from PyPI and compare their full SHA256 hashes with the
GitHub Release assets. Check the GitHub default-branch homepage separately:
merging documentation there does not update an existing PyPI description.

PyPI records release metadata from the first upload and does not update it
on subsequent uploads ([PyPI JSON API](https://docs.pypi.org/api/json/)). A
description correction therefore needs a new version through the existing
release process. Do not delete, replace or re-upload an existing release to
rewrite its description. Until the next release, link readers to the current
GitHub README and retain the old release's actual status in the launch notes.

## After the release

- Check CI is green on the tag, not just on main.
- Open the verdict gate's rotation PR (step 8c); until it merges, the gate
  still compares against the release before this one.
- `benchmarks/RESULTS.md` and `benchmarks/FAILURES.md` are generated. If the
  round changed anything they summarise, regenerate and commit them —
  `tests/test_state_claims.py` fails if they drift.
- If the round changed detector behaviour, the corpus sweep is not optional.
  If it changed only I/O or documentation, say which targeted checks stood in
  for it, in `DECISIONS.md`, by name.
