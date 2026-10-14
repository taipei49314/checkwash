# Releasing

The remediation candidate of D-055 shipped as v0.3.0 on 2026-09-07 — the
minor release its fingerprint and machine-interface break required
([upgrade notes](remediation-upgrade.md)). The promotion of the verified
fixed Action SHA under the one-release trust lag was a separate, later step:
v0.3.1 (2026-09-07) advanced the recommended pin to v0.3.0 (D-057) and v0.3.2
advanced it to v0.3.1 (D-058). The exact ledger-cleanup review is still a
separate governance change (D-055).

## Candidate, published source and delivered artifacts

Ordinary development runs the complete `pytest` collection, including the
performance gate, package/zipapp tests, and owned positive and negative tests
of `tools/verify_published_source.py`. The candidate package version remains
in `pyproject.toml` and `src/checkwash/__init__.py`. A development success is
not a receipt that the candidate is publicly installed.

`release/advertised.toml` separately names the actual public CLI release, its
peeled commit, native tag object and public zipapp bytes. README CLI install
commands follow this manifest. The unconditional `install-from-tag` job checks
that real remote tag in a clean checkout, installs it through the public Git
URL, verifies the installed commit and version, runs its demo and check, and
checks the public download's size and SHA256. A missing tag/download, a wrong
identity or any failed command makes that job fail. Candidate changes do not
silently advance the advertised release. Public capability claims cite the
versioned release guide; unreleased behavior is labelled as development work.

On an actual tag push, `published-source` also validates and installs the
event's own tag, independently of the advertised pointer. The source validator
requires the exact event commit and real remote/native tag identity, compares
`src/`, `pyproject.toml`, all of `action/` (including runtime Python drivers),
and `.pre-commit-hooks.yaml`, and rejects dirty public surfaces. Every Git
command must succeed. Source, tree, tag object and peeled commit are retained
in the receipt. Owned temporary Git repositories exercise these same checks in
ordinary CI; a local/private synthetic tag is never evidence of publication.

The release workflow repeats the native source/visitor validation for its own
release event. `build` cannot proceed on that event unless `published-source`
succeeds. Existing source, installed-wheel and actual-pyz assertion
qualification remains in place. Before distribution upload, all three
`tools/release_inventory.py` checks bind exact source and qualification
receipts to every wheel, sdist and pyz member and artifact digest. Diagnostic
receipts can upload after a failure; distribution assets cannot. Both GitHub
asset attachment and PyPI have successful source/build dependencies and remain
conditional on a real release event. They start in parallel once
`published-source` and `build` succeed; PyPI also requires `PYPI_ENABLED`
and the maintainer's approval of the `pypi` deployment.
`workflow_dispatch` builds and qualifies a candidate without publishing.

## Main first, then the tag

This procedure still requires explicit one-time authorization for the exact
version. Preparation of a candidate or of these workflows is not that grant.
The working-machine restriction remains: product runs, tests, qualification
and builds use the sanctioned hosted path; source inspection and draft edits
do not authorize local execution.

1. Prepare the authorized candidate version, source changes, release notes and
   limits. Keep README public install commands and `release/advertised.toml`
   on the last verified public release until the new release is publicly
   verified. Label candidate capability separately. Since 2026-10-14 the
   README's Action recommendation advances to this release once it is
   publicly verified (step 8), not one release later.
2. Open one release PR. Require its final exact head's hosted full development
   CI, source/wheel/pyz qualification and inventory, real current-advertised
   visitor checks, and `verdict gate` success. If the head changes, obtain new
   evidence for that head. Retain the actual checkout SHA and tree, since PR
   merge-checkout evidence and PR-head evidence have different subjects.
3. Merge through the normal required checks. A merge/squash/rebase creates a
   new commit: record it and compare its tree with the qualified head. Require
   the exact merge commit's `main` push CI and `verdict gate` success before
   creating a public tag. Missing, failed or cancelled required evidence stops
   publication; neither a local tag nor an expected red replaces it.
4. At that commit, `[baseline]` in `tests/verdict_gate/baseline.toml` still pins
   the previous release required by the tag-push gate: the highest other
   stable version tag merged into the commit, with its exact peeled commit.
   Do not rotate the baseline to obtain a green release verdict.
5. Only under the explicit publication grant, make the final annotated tag on
   the qualified merge commit and push only that tag. No ruleset is unlocked
   or restored any more (2026-10-14, below); the grant is what permits the
   push. Never move or delete an existing public tag to fix a failed check.
6. Require that tag's own `ci/published-source`, actual tag visitor, full CI and
   `verdict gate` successes, all bound to the same release commit. Record native
   run IDs and attempts. Failure leaves the tag public and the release stopped;
   the maintainer decides the remedy. README still advertises the previously
   verified release rather than prematurely offering this incomplete target.
7. Publish the authorized GitHub Release only after those receipts exist. Its
   workflow repeats exact source identity/visitor checks, qualifies the built
   distributions and validates all inventories before attaching assets or
   publishing to PyPI. `publish-assets` and the `pypi` job start in parallel
   once `published-source` and `build` succeed; the `pypi` job then waits for
   the `pypi` environment's required reviewer. The maintainer approves that
   deployment in GitHub, on the release workflow run's page under **Review
   deployments**, only after checking that the run belongs to the authorized
   tag and that `published-source`, `build` and `publish-assets` all
   succeeded, so PyPI never receives a version whose Release lacks its assets. An agent session cannot approve it. A rejected or expired
   approval leaves the Release without a PyPI version; the maintainer decides
   the remedy. A job success does not by itself establish that every
   external package service has delivered the expected bytes.
8. Download the actual GitHub/PyPI assets, compare identities and bytes, and
   execute the actual public visitor installation through the sanctioned path.
   Record source, native tag, distribution digests, complete run identities
   (including the release run whose `pypi` deployment was approved), result
   and limitations in the publication record. Advance the advertised manifest,
   the matching README CLI pins and the README Action pin to this release in a
   reviewed follow-up only once these checks pass. Failed historical receipts
   remain failed.
9. Separately rotate the verdict baseline after publication. `[baseline]`
   pins the new tag/version/commit and its actual pyz size/SHA256;
   `baseline_blocked` and `[t3.cases]` follow the gate's recorded proposal.
   `[canary]` keeps its v0.4.2 to v0.5.0 pair unless separately reviewed.
   Protected `tests/gates/verdict_gate_accepted.toml` and `DECISIONS.md` still
   need the maintainer's exact disposition; remove only the stale entries
   actually named by the rotation run. This remains separate from Action pin
   promotion and downstream re-pins.

Preparation for 1.0 stops before steps 5–9. The readiness report distinguishes
implemented publication checks from future execution against public objects
that do not yet exist. No preparation receipt claims a v1.0.0 public download
or visitor result.

## 2026-10-14: the PyPI deployment reviewer replaces the tag ruleset

On 2026-10-14 the maintainer decided to replace the tag ruleset as the
release gate with a required reviewer on the `pypi` environment, and then to
remove the ruleset without waiting for 1.0 ("先換真關卡再拿掉": put the real
gate in place first, then remove the old one). The `pypi` environment now
requires the maintainer's approval (reviewer `taipei49314`; self-review
allowed; administrators cannot bypass it). The tag ruleset
`release tags: cut only at the release slot` (22162219) was then deleted. The
branch ruleset `checkwash required` is unchanged.

The ruleset could not tell an agent holding the owner's token from the owner,
so it only turned tagging into a visible three-step. Agent sessions now use a
fine-grained token without the Administration or Deployments permissions:
they cannot change rulesets or approve the `pypi` deployment. They can still
create tags and GitHub Releases, so the technical gate now sits on the
irreversible step, the PyPI upload, rather than on the tag.

The rule itself is unchanged: every version bump, tag, GitHub Release and
PyPI publication still needs the maintainer's explicit one-time authorization
for that version, recorded in this file (`AGENTS.md` rule 5). A tag or Release
made without it violates that rule even though nothing technical rejects it,
and the maintainer does not approve the `pypi` deployment of an unauthorized
release. Nothing technical stops a tag from being moved or deleted either;
public tags are still never moved or deleted. As of this change, `AGENTS.md` rule 5
still says the tag ruleset rejects `v*` creation; that guardrail sentence
changes only through the maintainer.

The v0.7.0 entry below, the grants under "The release slot", `STATE.md` and
`docs/releases/` describe the ruleset as it was then and stay unchanged.

## v0.7.0 one-time publication authorization (2026-10-12)

After accepting the complete six-clause preparation proposal with “核准”, the
maintainer instructed **“發佈”** (publish) in the same conversation. This is the
one-time authorization for v0.7.0: integrate the reviewed stacked candidate,
record the exact accepted protected text and four #363 fixture labels, update
release-facing documentation, perform source-bound remote temporary-tag/full
qualification and final packaging checks, merge through the normal required
checks, and publish one v0.7.0 tag, GitHub Release and PyPI version. Necessary
remote qualification registration and dispatch remain within this release
procedure and run on the EC pool; no work-machine product execution is granted.

The exact accepted preparation proposal has SHA256
`8613b4b37a3bf1635623b87dd607ceb4ecb83a1d7c92b30c8ae6dd7255af4052`;
the human acceptance record has SHA256
`829c92e253aefbad57625654d486e7966675f68708f9fbd5e7c0d9ec3b3a9e23`.
The immutable READY review ZIP has SHA256
`9fad98171e9284fcbcd2152456dc939c651e950856f41fd1419eb6cd857a88eb`.
Approved protected wording is preserved exactly from diff SHA256
`c2a1181cbc947817cd261e98725f846a4d325fade693c596cdf39d98af648c7c`.
Its historical draft/pending language records the time of that proposal; the
later acceptance above is the applicable decision, without rewriting the
approved bytes or earlier raw failed/skipped receipts.

The tag ruleset (22162219, empty bypass list) may be disabled for the authorized
tag push only and must be restored immediately, before creating the Release.
The exact final-head PR verdict, main-push verdict and tag-push verdict are
required in the order above. The post-publication record will add their actual
run IDs/attempts, source/tree and package identities, public page/asset checks
and actual visitor-install results. Until those receipts exist, publication
completion is not claimed by this authorization entry.

The scope includes preparation of the post-publication verdict-baseline
rotation PR; its concrete maintainer-owned changes remain reviewable under
step 8c. It does not authorize another version or downstream re-pins of
checkwash-corpus or smallestlie. The Action remains pinned to prior stable
v0.6.0. T-528's original A–D work remains incomplete and CLAIMED.

### v0.7.0 actual publication record

This grant was consumed by publication at 2026-10-12T07:17:46Z from
`d647a65e9734f2b6e57b528ea595b1507dc31094`. PR verdict 38188853896,
main-push verdict 38214606358 and tag-push verdict 38215791171 each succeeded
on attempt 1, in that order. The tag ruleset was restored active before
Release creation. Release 38216943768/attempt 1 completed its build and PyPI
jobs; tag CI 38215791177/attempt 1 passed all 12 jobs including actual visitor
installation and the nine-platform byte comparison. The
[publication verification record](releases/v0.7.0-publication-verification.md)
records exact source/tree, public assets and SHA256s, package/page checks,
accepted macOS skips and retained earlier failed/skipped receipts. Verdict
baseline rotation remains a separate reviewable change; this does not grant
another release or downstream re-pins.

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
nothing is bumped, tagged or released. Since 2026-10-14 no tag ruleset
enforces this (see the dated section above): the authorization rule forbids
an unauthorized tag or Release, and the `pypi` environment's required
reviewer holds the PyPI upload until the maintainer approves it (step 7).
Record with that release's authorization the IDs and attempts of the main
verdict run that cleared the tag push, the tag verdict run that cleared
publication, and the release run whose `pypi` deployment the maintainer
approved. Historical grants below use the earlier procedure's step labels
(5b, 8a, 8c) and describe the tag ruleset (22162219, empty bypass list) that
rejected `v*` tag creation, update or deletion until 2026-10-14; their
unlock/push/restore sequences are records, not procedure.

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

## Release responsibility checks

- README CLI tag, pipx version and download URL match the explicit advertised
  public identity: `test_readme_install_refs_match_advertised_release`.
- Candidate source/package versions agree: `test_version_matches_pyproject`.
- The Action recommendation is hash-pinned and, since 2026-10-14, advances
  to the newest verified release instead of lagging one release behind:
  `test_readme_action_snippet_is_zizmor_blanket` checks the pinning.
- The actual public tag exists and its complete install surfaces have the
  expected source/native identity: `tools/verify_published_source.py`, in the
  advertised visitor, tag-event job and release prerequisite. Its failure
  paths run in ordinary `test_published_source.py` owned fixtures.
- Candidate source/wheel/pyz behavior remains qualified by
  `assertion-qualification.yml`; delivered archives are bound by
  `release_inventory.py` before any distribution upload.
- STATE's authoritative `version` row is the development package version;
  its separately labelled last-public-release fields follow the manifest.

## Why neither phase gets an escape hatch

The historical `test_pinned_tag_ships_the_current_source` existed because
**v0.1.0 pointed two fixes behind main**: people installed the pre-fix engine
while reading post-fix claims. On 2026-08-08 a missing-tag early return was
added and removed the same day. Passing because the subject is absent remains
prohibited. These historical facts and failed receipts are unchanged.

The replacement preserves that responsibility at the phase that can actually
prove it. Ordinary candidate CI runs the same validator against controlled
positive/negative Git identities and verifies the already-advertised public
release. Tag and release jobs require the real new public identity. No missing
subject becomes a skip-success, and no new capability is advertised as shipped
merely because the candidate passes. The prior policy of treating routine
candidate/tag divergence as an expected development failure is superseded by
this explicit separation; no test selection or `continue-on-error` hides it.

The verdict gate continues to require success on the release PR's final head,
then the exact release commit on main, then that same commit on the public tag.
A failed, cancelled or missing run stops publication. A BLOCK-to-PASS still
requires a repair or the maintainer's recorded acceptance; this phase change
supplies no such acceptance.

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
a separate job because the recommended pin can trail the candidate on `main`
and so expose real capability gaps. Until 2026-10-14 the pin also lagged one
release behind (for example, the v0.5.0 pin lacked the v0.6.0 work on the
reports and rulings that followed #172–#181); it now advances to each newly
verified release. Its actual result is measured independently. The job
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
since 0.2.1 has also published to PyPI (`pipx install checkwash`). A published
release proceeds to PyPI once the maintainer approves the `pypi` deployment,
and the wheel and sdist on PyPI are the same
bytes the `build` job attached to the release (checked on 0.2.11,
2026-09-02). That approval was added on 2026-10-14 (step 7). The `pypi` job publishes
through trusted publishing, so no token is stored anywhere by anyone. The
approval is a gate only if the PyPI trusted publisher names the `pypi`
environment: the `release` event runs the `release.yml` of the tagged
commit, so without that binding a tag on a commit whose workflow omits the
environment could still upload. The three steps
that opened the gate, all the maintainer's:

1. Register checkwash as a trusted publisher on PyPI for this repository and
   the `release` workflow.
2. Set the repository variable `PYPI_ENABLED` to `true`.
3. Keep the `pypi` environment for its deployment protection rules. Since
   2026-10-14 that rule is a required reviewer: the maintainer
   (`taipei49314`), self-review allowed, no administrator bypass.

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
- Open the verdict gate's separate rotation PR (step 9); until it merges, the gate
  still compares against the release before this one.
- `benchmarks/RESULTS.md` and `benchmarks/FAILURES.md` are generated. If the
  round changed anything they summarise, regenerate and commit them —
  `tests/test_state_claims.py` fails if they drift.
- If the round changed detector behaviour, the corpus sweep is not optional.
  If it changed only I/O or documentation, say which targeted checks stood in
  for it, in `DECISIONS.md`, by name.
