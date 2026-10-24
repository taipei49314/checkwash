# PJU release handoff proposal

This proposal prepares the missing main, tag, release-event and public-visitor
route after the PR receipt bridge. Its starting source is
`5338e6894d3a1880acb0376ce700ac0d571dbcdc`. The release workflow is still
disabled. The included offline identity prototype cannot issue checks or publish
distributions. There is no authorization here to bump a version, merge, tag or
release. The next version remains provisional v0.9.1.

## Current implementation and proposed changes

| Surface | Current behavior | Proposed change |
| --- | --- | --- |
| `collect_pju_receipts.py` and `pju_receipt_bridge.py` | Full local PR evidence; live open head/base; four existing required contexts | Preserve PR behavior; add a separate collector and verifier for release stages |
| `release.yml` | Disabled; combines hosted product execution and publication | Separate metadata capture, PJU execution, read-only evidence verification and credentialed upload |
| `ci.yml` and `verdict-gate.yml` | Disabled test workflows | Keep disabled; execute their required product checks through PJU stage collectors |
| `quality-candidate-intake.yml` | Active PR bridge | Do not reinterpret its PR-only success as main, tag or release success |
| Platform coverage | Existing PR bridge accepts Windows/Python 3.11.9 only | Record each real leg and every missing leg; resolve version acceptance separately |

## Stage subjects and evidence

Each stage binds repository, exact commit and full tree, native event name,
run ID, exact attempt, reviewed workflow SHA, collector SHA, immutable evidence
commit and external manifest digest. Native observations come from a trusted
GitHub adapter, never from a candidate-supplied URL or author field. The event
capture workflow does data collection only, with `contents: read`; its own
success means an event was captured, not that product checks passed.

| Stage | Additional subject | Fresh evidence before advancing |
| --- | --- | --- |
| PR | Open same-repository PR number and actual head/base | Existing four required contexts, complete full-suite raw/JUnit, qualifications and inventories, real pinned/candidate Action replay; release PR also needs visitor and verdict evidence |
| main | `refs/heads/main`, actual push event, merge commit and first parent | Exact merge-commit execution, source and package inventories, advertised visitor and verdict gate; record comparison with reviewed PR tree |
| tag | Tag-push event, complete annotated tag object and peeled commit | Native remote tag/source readback, actual Git-tag fresh visitor, full development/qualification/inventory and tag-specific verdict gate |
| release-event | Native published Release ID, event payload digest and event run/attempt, native tag object | Event-after-source validation, actual Git-tag visitor, fresh build, source/wheel/pyz qualifications and all inventories |
| public-visitor | Verification dispatch run plus the exact prior Release event, asset IDs and PyPI filenames/URLs | Independently download GitHub wheel/sdist/pyz and PyPI wheel/sdist, compare actual bytes, run fresh installations and visitors |

Each stage resolves the previous stage's successful verification report by
immutable digest. A report must prove that prior stage's own subject and complete
evidence. Merely copying a digest is insufficient. Same tree does not make two
commits identical; same peeled commit does not make two tag objects identical.
PR, main, tag, release-event and public-visitor reports remain distinct even when
they refer to the same product source.

Main/tag metadata capture needs a newly reviewed workflow such as
`pju-release-events.yml`, triggered on main pushes, tag pushes and
`release: published`. It must not invoke product code. Initial bootstrap may
capture the merge that introduces it; no earlier push event may be invented.
The trusted adapter checks native run event, exact attempt, workflow path/SHA,
source/ref and event artifact bytes against readbacks. Collection starts after
the corresponding event; local timestamps alone are not remote attestation.

## Release event and publication sequence

The existing published-release event has no receipt commit/digest input. Fresh
evidence for that event cannot exist before it occurs. Use two explicit steps:

1. Capture and freeze the native published event: repository, Release ID,
   tag name/object/peeled source, native run/attempt, workflow SHA and event
   artifact digest. This does not upload distributions.
2. PJU collects the event's fresh source/visitor/build/qualification evidence.
   An authorized publisher stores it immutably. A maintainer-authenticated
   `workflow_dispatch` on the reviewed `.github/workflows/release.yml` admits
   that exact event, evidence commit and external digest.

Publication uses the fresh release-event build as its unique distribution set.
Do not assume it equals a pre-event build; bind every member and actual
wheel/sdist/pyz size and digest to the event's qualified source. Rebuilding later
invalidates that distribution admission and needs new matching qualification.

The future `release.yml` job graph is:

```text
native event capture -> PJU event collection -> immutable evidence/readback
  -> verify evidence and live native subject (contents read)
  -> attach exact GitHub assets and verify actual readback (contents write)
  -> PyPI deployment waits for Nelson (id-token write, environment pypi)
  -> PJU public downloads/installations -> reviewed pin promotion
                                      -> separate baseline rotation
```

Keep the trusted-publisher filename `release.yml`, `environment: pypi`,
`vars.PYPI_ENABLED == 'true'` and minimal per-job OIDC permission. Make PyPI
depend on the successful GitHub asset upload/readback, preserving the existing
human condition mechanically. Nelson alone approves the deployment. Before
enabling publication, read back the actual PyPI trusted-publisher registration,
including its environment, and verify the proposed dispatch/ref claims; the
repository documents do not prove the live service registration.

Before upload and again after approval, read back the Release ID, public/draft
state, tag name/object/peeled source, admitted run and distributions. Reject
deleted/recreated Releases or moved tags. If an asset already exists, identical
downloaded bytes may be retained; different bytes stop the run. Remove the
current blanket `--clobber` behavior from the proposed publisher. PyPI publication
does not retry automatically after unknown outcome: reconcile actual public
files first, retain the original failure, and obtain any necessary new decision.

## Collector and verifier contract to implement

The local collector runs from an independently reviewed clean checkout. Product
subprocesses receive an allowlisted environment with no GitHub/PyPI credentials.
Publishers do not execute candidate Python, shell, Action code, archives,
installers or tests. They inspect source/archive/JSON/XML bytes with trusted
code, under bounded file sizes, counts and paths.

The full stage manifest must include:

- Stage subject and native capture digest; complete actual host/runtime/tool
  identities; source commit, tree and cleanliness before and after collection.
- Every required command's exact argv/cwd, raw streams, start/finish, timeout
  state and actual exit. Full development collection includes performance,
  package/zipapp and published-source positive/negative tests. Preserve failure
  receipts; absence is never success.
- Authoritative qualification case inventory and all source/wheel/pyz case
  observations, complete delivered archive-member inventories and artifact
  digests. A summary `passed` field cannot replace raw evidence.
- Native/public source verification, visitor commands and actual installed
  identity, with each path attributed to advertised, event tag or final public
  distributions as appropriate. Tag visitor does not require future Release
  assets that do not exist yet.
- Verdict gate inputs/identities, previous highest stable baseline, protected
  acceptance file, complete cases/canary/results and raw exits. R29's two
  1,800-commit sets remain a separately approved comparison and owner review.
- Executed platform legs, absent legs marked `NOT_RUN`, and separately resolved
  source/version-specific human acceptance if the full matrix is missing.

The release-stage verifier and publisher independently repeat validation. A
successful PR bridge report cannot substitute for these validators. Missing
native capture, evidence, prior report or platform disposition stops stage
advancement. Stage-labelled verification output must say which actual PJU scope
it covers; do not create the names of old hosted test jobs to imply they ran.
Existing PR ruleset contexts and App binding stay unchanged.

## Platform acceptance

The standing venue policy authorizes execution on PJU; it does not supply
Linux/macOS or Python 3.12/3.13 evidence. The frozen determinism contract remains
Linux/macOS/Windows on Python 3.11–3.13, with cross-leg byte comparison.

Choose the version's acceptance after its final source and actual capability
table exist. Either supply the nine real legs and comparisons, or ask Nelson
for a version/source-specific waiver naming every missing leg/comparison and
the exact public wording. A waiver records acceptance of absent evidence; it
does not turn absent legs into PASS or rewrite the standing contract. Changing
that contract requires the separate minor-version review.

## Prototype and implementation acceptance

`tools/pju_release_identity.py` checks exact stage/native-object fields and
admitted digest links against three supplied JSON values. It rejects stage
replay, stale subjects, different native attempts, lightweight tags and malformed
identities. Even on success it returns `identity-matched-only` and
`publication_allowed: false`. Its inputs do not authenticate themselves.

The prototype has no network, check publisher, token handling, collector,
timestamp validation, deep receipt verifier or artifact-byte validation. Parent
digests are matched, not resolved. Do not connect its exit 0 to a publishing job
or describe the prototype tests as completed release qualification.

Before the complete route can operate, implement and independently review the
native capture/adapter, credential-free stage collector, deep verifier and
publisher changes above. Exercise owned negative cases for stale main, PR-to-main
reuse, changed annotation/peeled source, wrong Release ID/attempt, pre-event
receipts, failed/partial raw commands, incomplete qualification inventories,
changed artifact bytes, unaccepted missing platforms, stale approval and public
download/installation failure. No successful check or upload may occur in those
cases. Run actual final PR dogfood and required checks before a normal merge;
bootstrap the new release route through data-only verification on reviewed
workflow code without bypassing protections.
