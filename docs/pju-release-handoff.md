# PJU release evidence and publication handoff

This checkout implements PR, main, tag, release-event and public-visitor
collection, deep verification and the publication handoff. Independent review,
the final full suite and native end-to-end verification are still pending.
Source implementation and owned tests do not prove an actual GitHub dispatch,
check, asset upload or PyPI publication. Writing YAML does not enable a disabled
workflow. Record real native results as they occur. This document grants no
version bump, merge, tag, release, platform waiver or deployment approval.

The [PJU primary policy, T-610](https://github.com/taipei49314/estate-consolidation/blob/103c52abd38eb87c13980aa7cf6f0db4412e53ac/POLICY.md)
authorizes PJU execution without a Tuesday expiry. Nelson stopped investigation
of the current pool outage; do not poll it. Capable pool hosts may later supply
their own evidence. This implementation verifies actual Windows/Python 3.11.9
receipts from LAPTOP-01AGNPJU, labelled
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`; other platforms remain `NOT_RUN` here.

## Implemented components and subjects

| Component | Implemented behavior |
| --- | --- |
| `collect_pju_receipts.py` / `pju_receipt_bridge.py` | Existing PR collection and four required contexts remain available |
| `collect_pju_release.py` | One fresh shared-backend collection per real stage, with release-specific work; no synthetic PR ID |
| `pju_release_bridge.py` | Native capture, deep data verification, distinct checks, exact asset upload/readback and protected PyPI handoff |
| `quality-candidate-intake.yml` | Adds `release-capture` and `release-receipt` for PR bootstrap on reviewed code; preserves legacy modes |
| `release.yml` | Hosted metadata capture/verification and credentialed publication; product execution is local |
| `pju_release_identity.py` | Earlier offline prototype only; `identity-matched-only`, `publication_allowed: false`; never a publishing gate |

The hosted bridge never executes candidate product code, installers, tests,
Action helpers or archive members. The independent local collector uses an
allowlisted child environment with no GitHub/PyPI credentials. Owner-admitted
immutable evidence is the trust boundary, not hardware attestation. Verifier
and publisher independently repeat validation; author fields and summary flags
cannot authenticate a receipt.

A collection runs the full development suite, actual pinned/candidate Action
replay, source/wheel/pyz qualification and inventories, twine, the process-level
zipapp contract, advertised visitor and verdict gate. It retains original
commands/exits/streams, nested helper raw offsets, actual runtime and source
checks before and after. The release-event stage builds fresh distributions
after its event. Public-visitor instead qualifies the actual downloaded GitHub
bytes, downloads PyPI wheel/sdist too, compares all five files, performs four
fresh artifact installations plus the Git-tag visitor, and exercises public pyz.

| Stage | Real native subject | Required previous report |
| --- | --- | --- |
| `pr` | Owner manual dispatch; live open same-repository PR number/head/base/tree | None; `parents` is `{}` |
| `main` | Owner manual dispatch; live main commit/tree and first parent | New PR stage report, PR stage check and four required contexts |
| `tag` | Owner manual dispatch; annotated public tag object and peeled source | Main stage report/check |
| `release-event` | Real `release: published` event, Release ID/tag/source/run/attempt | Tag stage report/check |
| `public-visitor` | Owner manual dispatch; exact existing Release/tag/source and public files | Release-event report/check |

Manual main/tag captures are not push runs. PR base is the live PR base, which
need not equal the head's first parent. Other stages retain the release commit's
first parent. Identical source or trees do not make stages interchangeable.
New PR collection runs its release extras in the same backend, not a duplicate
suite. Its publisher creates the unchanged four required contexts/App binding
and `PJU release evidence (pr)`. Other stages create their own
`PJU release evidence (<stage>)` check only. A legacy four-green PR report alone
does not prove the new PR visitor/verdict extras.

## 1. Prepare reviewed sources and capture native metadata

Prepare clean fixed checkouts with `core.autocrlf=false`: trusted collector,
candidate, pinned Action, separate candidate Action when its closure differs,
and the pinned verdict canary sources. Keep the fresh admitted Python 3.11.9
venv, receipt and scratch outside every source checkout. Its externally hashed
package-name/version dependency JSON must include reviewed build/test packages
and twine. Collector and verifier/workflow sources are separately admitted.

These PowerShell examples are templates, not grants. Replace all placeholders
with saved native readbacks; example `v0.9.1` does not authorize that version.
Use a task directory outside the checkouts:

```powershell
$ReleaseWork = 'C:\task\checkwash-release'
$ReviewedRef = 'REVIEWED_BRANCH_OR_TAG'
$WorkflowSha = 'FULL_REVIEWED_WORKFLOW_SHA'
$CandidateSha = 'FULL_CANDIDATE_SHA'
$Stage = 'pr'
$Capture = [ordered]@{
  schema_version=1; kind='checkwash.pju-release-capture.v1'
  stage=$Stage; head=$CandidateSha; tag=$null; release_id=$null
  trusted_workflow_sha=$WorkflowSha; pr_number=563 # actual open PR
}
@{mode='release-capture'; admission=($Capture | ConvertTo-Json -Compress)} |
  ConvertTo-Json -Compress |
  gh workflow run quality-candidate-intake.yml --repo taipei49314/checkwash --ref $ReviewedRef --json
```

PR bootstrap uses the active intake entry on the reviewed branch. The native
run must resolve to the admitted workflow SHA. After normal merge and review,
enable only the rewritten `release.yml` when authorized, keeping the old hosted
product-test workflows disabled. Other manual captures use `release.yml`,
`mode=capture`, with these capture-admission changes:

| Stage | `head` | `tag` | `release_id` | `pr_number` |
| --- | --- | --- | --- | --- |
| `main` | Exact current main commit | `null` | `null` | Omit |
| `tag` | Exact release commit | `"v0.9.1"` | `null` | Omit |
| `public-visitor` | Same release commit | `"v0.9.1"` | Actual integer Release ID | Omit |

```powershell
@{mode='capture'; admission=($Capture | ConvertTo-Json -Compress)} |
  ConvertTo-Json -Compress |
  gh workflow run release.yml --repo taipei49314/checkwash --ref $ReviewedRef --json
```

There is no manual `release-event` capture admission. The authorized GitHub
Release's real published event triggers capture automatically, after the tag's
own evidence has passed. The reviewed workflow must already exist on that tagged
commit. This first event uploads metadata only, not distributions; fresh event
evidence cannot exist before the event.

Read back the exact capture run/attempt/event/workflow path/SHA/source/actor and
successful completion. Do not select an unrelated latest run or another attempt.
Download its precisely named artifact, preserving both files unchanged:

```powershell
$CaptureRun = 123456 # actual run, not a literal to reuse
$CaptureAttempt = 1
$CaptureDir = Join-Path $ReleaseWork "captures\$CaptureRun-$CaptureAttempt"
gh api "repos/taipei49314/checkwash/actions/runs/$CaptureRun/attempts/$CaptureAttempt"
gh run download $CaptureRun --repo taipei49314/checkwash --name "pju-release-subject-$CaptureRun-$CaptureAttempt" --dir $CaptureDir
$SubjectPath = Join-Path $CaptureDir 'subject.json'
$PayloadPath = Join-Path $CaptureDir 'event-payload.json'
$SubjectSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $SubjectPath).Hash.ToLowerInvariant()
```

The exact subject shape is below; only PR adds `pr_number`. Main has null
tag/object/release ID; tag has null release ID; subsequent stages have the real
Release ID. `event.name` is `release` only for release-event, otherwise the actual
`workflow_dispatch`. The bridge re-reads these native objects:

```json
{
  "schema_version": 1, "kind": "checkwash.pju-release-subject.v1",
  "stage": "pr", "repository": "taipei49314/checkwash", "pr_number": 563,
  "head_sha": "FULL_NATIVE_HEAD_SHA", "base_sha": "FULL_NATIVE_BASE_SHA",
  "source_tree": "FULL_NATIVE_TREE_SHA", "tag": null, "tag_object": null,
  "release_id": null,
  "event": {
    "name": "workflow_dispatch", "run_id": 123456, "run_attempt": 1,
    "workflow_sha": "FULL_CAPTURE_WORKFLOW_SHA", "created_at": "NATIVE_UTC_TIMESTAMP",
    "payload_sha256": "SHA256_OF_EXACT_EVENT_PAYLOAD_BYTES"
  }
}
```

## 2. Collect one fresh stage on PJU

PR's external `parents.json` is `{}`. Later stages copy the previous successful
new stage report, without reserializing it, into
`parent-reports/parents/<stage>.json`. Main's parent example is:

```json
{"pr":{"report":"parents/pr.json","sha256":"SHA256_OF_EXACT_REPORT_BYTES","check_run_id":123457}}
```

Use parent keys `main`, `tag` and `release-event` for the following stages.
For the PR parent, the link's ID is the actual `checkwash` context ID in
`check_run_ids`; the separate report `check_run_id` is the PR stage check. Both
it and all four contexts are read back. For other parents use their stage check
ID. Native App/name/head/success/external-ID linkage must match, not just a JSON
status or copied digest.

```powershell
$TrustedRoot = Join-Path $ReleaseWork 'trusted-collector'
$CandidateRoot = Join-Path $ReleaseWork 'candidate'
$PinnedActionRoot = Join-Path $ReleaseWork 'action-v090'
$CandidateActionRoot = Join-Path $ReleaseWork 'candidate-action'
$PythonExe = Join-Path $ReleaseWork "venvs\$Stage-$CaptureRun\Scripts\python.exe"
$CollectorSha = 'FULL_REVIEWED_COLLECTOR_SHA'
$LockPath = Join-Path $ReleaseWork "locks\$Stage-$CaptureRun.json"
$ParentRoot = Join-Path $ReleaseWork 'parent-reports'
$ParentsPath = Join-Path $ReleaseWork "admissions\$Stage-parents.json"
$StageRoot = Join-Path $ReleaseWork "runs\$Stage-$CaptureRun-$CaptureAttempt"
$ReceiptRoot = Join-Path $StageRoot 'receipt'
$ScratchRoot = Join-Path $StageRoot 'scratch'
$CollectorArguments = @(
  '-I','-B','-X','utf8',(Join-Path $TrustedRoot 'tools\collect_pju_release.py'),
  '--source-root',$CandidateRoot,'--action-root',$PinnedActionRoot,
  '--candidate-action-root',$CandidateActionRoot,
  '--python',$PythonExe,'--git','C:\Program Files\Git\cmd\git.exe',
  '--bash','C:\Program Files\Git\bin\bash.exe',
  '--collector-source-sha',$CollectorSha,
  '--dependency-lock',$LockPath,
  '--dependency-lock-sha256',(Get-FileHash -Algorithm SHA256 -LiteralPath $LockPath).Hash.ToLowerInvariant(),
  '--subject',$SubjectPath,'--subject-sha256',$SubjectSha,'--event-payload',$PayloadPath,
  '--parents',$ParentsPath,
  '--parents-sha256',(Get-FileHash -Algorithm SHA256 -LiteralPath $ParentsPath).Hash.ToLowerInvariant(),
  '--parent-report-root',$ParentRoot,
  '--verdict-canary-old-source',(Join-Path $ReleaseWork 'canary-v042'),
  '--verdict-canary-new-source',(Join-Path $ReleaseWork 'canary-v050'),
  '--output',$ReceiptRoot,'--scratch',$ScratchRoot
)
```

Baseline and advertised source default to pinned Action only when its exact
commit matches those pins. Supply `--verdict-baseline-source` and
`--advertised-source` if different. Canary checkouts retain their fixed
v0.4.2/v0.5.0 source commits/tags; the collector downloads and verifies their
real public pinned pyz files rather than building substitutes.

For release-event, add the true external human records before the packet seals:

```powershell
$ReleaseAuthorization = Join-Path $ReleaseWork 'admissions\release-authorization.json'
$PlatformAcceptance = Join-Path $ReleaseWork 'admissions\platform-acceptance.json'
$CollectorArguments += @(
  '--release-authorization',$ReleaseAuthorization,
  '--release-authorization-sha256',(Get-FileHash -Algorithm SHA256 -LiteralPath $ReleaseAuthorization).Hash.ToLowerInvariant(),
  '--platform-acceptance',$PlatformAcceptance,
  '--platform-acceptance-sha256',(Get-FileHash -Algorithm SHA256 -LiteralPath $PlatformAcceptance).Hash.ToLowerInvariant()
)
```

They are saved at `release/release-authorization.json` and
`release/platform-acceptance.json`. Inclusion is data custody, not approval.
Proposed records do not become accepted. Publication requires real exact-version
and source-specific human decisions, actual quotes and evidence references.

For public-visitor instead admit the release-event report's actual artifact map.
The values below are placeholders, not acceptable release bytes:

```json
{
  "checkwash-0.9.1-py3-none-any.whl":{"bytes":123,"sha256":"ACTUAL_RELEASE_WHEEL_SHA256"},
  "checkwash-0.9.1.tar.gz":{"bytes":456,"sha256":"ACTUAL_RELEASE_SDIST_SHA256"},
  "checkwash.pyz":{"bytes":789,"sha256":"ACTUAL_RELEASE_PYZ_SHA256"}
}
```

```powershell
$ArtifactMap = Join-Path $ReleaseWork 'admissions\release-artifacts.json'
$CollectorArguments += @(
  '--release-artifacts',$ArtifactMap,
  '--release-artifacts-sha256',(Get-FileHash -Algorithm SHA256 -LiteralPath $ArtifactMap).Hash.ToLowerInvariant()
)
```

For every stage, execute its assembled arguments after appending only that
stage's applicable flags:

```powershell
# Retain this outer command's real stdout/stderr and exit as well as its packet.
& $PythonExe @CollectorArguments
if ($LASTEXITCODE -ne 0) { throw 'Collection failed; preserve the complete raw packet.' }
$ManifestSha = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $ReceiptRoot 'manifest.json')).Hash.ToLowerInvariant()
```

Run the assembled arguments once for the intended stage. Output and scratch
must be fresh. The manifest is
`checkwash.pju-release-receipt.v1`, with subject/parents and no synthetic top-level
PR number. `release/collection.json` records final timing/status. The packet
includes native payload, parent records, command/nested raw, qualifications,
inventories, distributions and visitors. Existing 5,000-file/1 GiB bounds remain;
missing, failed, changed or oversized evidence is not success.

## 3. Immutable evidence, verification and check readback

The authorized publisher stores reviewed packet bytes at `receipt/` in an
immutable commit in **`taipei49314/checkwash`**, then reads the commit and every
file back. Workflows check out `receipt_commit` from that repository; a private
Lab SHA is not a substitute. Venv/scratch are not evidence-commit contents.
This data publication is distinct from a GitHub Release or PyPI upload.

Use this exact dispatch shape; only PR includes `pr_number`:

```json
{
  "schema_version":1,"kind":"checkwash.pju-release-dispatch.v1","stage":"pr",
  "head":"FULL_NATIVE_HEAD_SHA","base":"FULL_NATIVE_BASE_SHA",
  "tag":null,"release_id":null,"pr_number":563,
  "receipt_commit":"FULL_IMMUTABLE_EVIDENCE_COMMIT",
  "manifest_sha256":"ACTUAL_MANIFEST_SHA256",
  "collector_source_sha":"FULL_REVIEWED_COLLECTOR_SHA",
  "trusted_workflow_sha":"FULL_REVIEWED_VERIFIER_WORKFLOW_SHA",
  "subject_sha256":"ACTUAL_CAPTURE_SUBJECT_SHA256",
  "release_authorization":null,"platform_acceptance":null
}
```

For bootstrap PR, intake `release-receipt` runs separate verification and check
publication jobs; both deeply validate the same admitted bytes:

```powershell
$DispatchPath = Join-Path $ReleaseWork "admissions\$Stage-dispatch.json"
$DispatchJson = Get-Content -Raw -LiteralPath $DispatchPath
@{mode='release-receipt';admission=$DispatchJson} | ConvertTo-Json -Compress |
  gh workflow run quality-candidate-intake.yml --repo taipei49314/checkwash --ref $ReviewedRef --json
```

After bootstrap, `release.yml` mode `verify` is read-only. Mode `publish` adds
stage checks; for release-event it also uploads distributions and reaches the
protected PyPI deployment, so it is not a dry run:

```powershell
@{mode='verify';admission=$DispatchJson} | ConvertTo-Json -Compress |
  gh workflow run release.yml --repo taipei49314/checkwash --ref $ReviewedRef --json
# Only for an admitted, authorized publication of the intended stage:
@{mode='publish';admission=$DispatchJson} | ConvertTo-Json -Compress |
  gh workflow run release.yml --repo taipei49314/checkwash --ref $ReviewedRef --json
```

Release-event publication uses two non-null dispatch links to its sealed files:

```json
{
  "release_authorization":{"path":"release/release-authorization.json","sha256":"ACTUAL_AUTHORIZATION_RAW_SHA256"},
  "platform_acceptance":{"path":"release/platform-acceptance.json","sha256":"ACTUAL_ACCEPTANCE_RAW_SHA256"}
}
```

The event-after fresh build is the unique admitted distribution set. A later
rebuild needs matching new evidence. Existing GitHub assets are retained only
when actual downloaded bytes match; differences stop publication. There is no
blanket `--clobber`. Reconcile unknown outcomes before any further authorized
action; no automatic retry is supplied.

Read back each actual run/attempt and native check: name, Actions App ID `15368`,
head, success, external ID, manifest digest, receipt commit and details URL.
PR's four external IDs remain `pju:<manifest>:<context>`; stage checks use
`pju-release:<manifest>:<stage>`. A skipped job is not a successful product check.
Retain the exact named artifacts:

- `pju-release-verification-<run>-<attempt>`: verification result.
- `pju-release-stage-check-<run>-<attempt>`: published report with four PR
  `check_run_ids` and separate stage `check_run_id`, when applicable.
- `pju-release-assets-<run>-<attempt>`: actual GitHub asset readback.
- `pju-pypi-handoff-<run>-<attempt>`: post-approval source/asset check.

For example, retrieve a completed publisher's report and inspect every native
check it names. Compare the returned fields with the admitted subject/digest and
the required names above before advancing:

```powershell
$PublisherRun = 123458 # actual publisher run
$PublisherAttempt = 1
$ReportDir = Join-Path $ReleaseWork "reports\$PublisherRun-$PublisherAttempt"
gh run download $PublisherRun --repo taipei49314/checkwash --name "pju-release-stage-check-$PublisherRun-$PublisherAttempt" --dir $ReportDir
$ReportPath = Join-Path $ReportDir 'release-stage-check.json'
$StageReport = Get-Content -Raw -LiteralPath $ReportPath -ErrorAction Stop | ConvertFrom-Json
$NativeCheckIds = @($StageReport.check_run_ids) + @($StageReport.check_run_id)
foreach ($NativeCheckId in $NativeCheckIds) {
  gh api "repos/taipei49314/checkwash/check-runs/$NativeCheckId" --jq '{id,name,head_sha,status,conclusion,external_id,details_url,app_id:.app.id}'
}
$ParentReportSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ReportPath).Hash.ToLowerInvariant()
```

Use the published stage report's original bytes as the next parent. A read-only
verify report without a native check ID cannot replace it.

## 4. Complete the authorized version

Follow [RELEASING](RELEASING.md): final PR evidence and normal merge; exact main;
authorized annotated tag and its own evidence; authorized GitHub Release;
event-after fresh build/qualification; actual assets; Nelson's PyPI approval;
real public downloads/installations. R29's two fixed 1,800-member sets and owner
review remain separate from verdict cases and #419 history.

PyPI retains filename `release.yml`, `environment: pypi`,
`vars.PYPI_ENABLED == 'true'` and per-job `id-token: write`. It depends on
successful actual GitHub asset readback, then repeats verification after Nelson
approves the deployment. Agents cannot approve it. Before enabling this path,
read back the live PyPI trusted-publisher registration, environment and dispatch/
ref compatibility; repository documentation alone does not establish that setup.

This verifier certifies Windows/Python 3.11.9 only. All eight other matrix legs
and cross-platform byte comparison remain `NOT_RUN` here. Its publisher requires
real version/source-specific acceptance of those missing items while preserving
the standing nine-leg contract. Supplementary Linux evidence is not silently
certified by this packet. A different acceptance table or full-matrix route
requires an explicitly reviewed extension, not invented coverage or a contract
rewrite inside this patch.

Advance reviewed advertised/README/Action pins only after the new public-visitor
packet and native check succeed. Preserve failed historical receipts and record
actual source, tag, runs, bytes, visitors and limits. Rotate verdict baseline in
a separate reviewed change. Downstream re-pins and issue closure keep their own
applicable authorization.
