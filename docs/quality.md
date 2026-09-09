# Quality configuration review

This branch implements the owner-approved quality expansion design. It is an
unreleased preview, separate from `checkwash check`. The release remains v0.3.3;
no release or downstream pin is changed by this work.

`checkwash quality BASE...HEAD` reviews declared configuration requirements.
It does not execute repository code, inspect live branch rules, or verify that
CI actually ran the declared tools. No network access or external tool process
is used by the quality core. Development qualification runs pinned tools only
against trusted synthetic fixtures on existing hosted CI.

## Use

```text
checkwash quality BASE...HEAD
checkwash quality BASE..HEAD --format json
checkwash quality --format sarif
checkwash quality profiles
checkwash quality explain QW_THRESHOLD_LOWERED
```

Targets and enforcement are read only from the base revision's
`.checkwash/quality.toml`. With no base targets, discovery reports declarations
and `incomplete`, never an assertion of effective enforcement.

```toml
schema_version = 1
mode = "report"

[[targets]]
id = "coverage-main"
tool = "coverage"
root = "."
config = "pyproject.toml"
profile = "coverage-7.16.0-q1"
paths = ["src/"]
version_files = ["uv.lock"]
```

Profile IDs become available only when their generated package-owned models
are included with this branch. `quality profiles` is the authoritative inventory.
Unknown profiles are incomplete, never an implicit current-version model.

Report mode leaves findings visible and returns 0 for observed weakening or
unsupported semantics. Enforce mode returns 1 for unexempted high/critical
findings and 2 for incomplete analysis. Errors return 2 in either mode. If
snapshot construction fails before base policy can be established, the run is
an error, not a report-mode fallback. JSON explicitly carries mode, completeness
and verdict; consumers must not interpret a report exit 0 as enforcement.

## Current implementation boundary

- Coverage: integral `report.fail_under` comparisons under unchanged, known
  precision/measurement context; limited literal path and directory/** scope.
- Ruff: qualified rule catalog selection/ignore comparison; bounded root
  configuration scope. Preview settings, unqualified selection context,
  per-file overrides and gitignore-dependent scope remain incomplete.
- Mypy: explicitly listed global check flags and a small default error-code
  set. General strict expansion, inline directives, overrides and regex scope
  remain incomplete.
- Configuration source inventory includes higher-priority candidate absence,
  selected source contents and declared version-source changes.

At the initial implementation checkpoint, Ruff extend merging and nested auto
configuration are detected but remain incomplete. The approved design includes
their later qualification; this checkpoint does not claim that work complete.
The strict snapshot reader retains its existing 1,000,000-byte per-file limit,
slightly below the draft's 1 MiB proposal. Limits and unsupported settings are
visible and cannot be exempted.

## Exemptions

Use `.checkwash/quality-allow.toml` with one `[[allow]]` entry per exact finding.
Required string fields: fingerprint, rule, target_id, reason, author, created,
expires. Only the three high weakening rules accept exemptions. A valid entry
must already exist at base, have a complete q1 SHA256 identity and expire within
180 days of creation. The date is reproducible through the CLI's existing
CHECKWASH_TODAY / GREENWASH_TODAY override.

Head additions are visible but cannot exempt the current PR. Changed contents,
profile or relevant source selection need a new review. Existing `check`
guardrail behavior for `.checkwash/**` remains in effect; quality does not
suppress its findings. Installation/approval should occur through the existing
maintainer governance process before enforcement is enabled.

## Validation and integration

The approved detailed proposal is in [the design document](design/quality-v0.4.md).
The separate report contract is [quality schema 1](quality-report.schema.json).
Legacy findings schema 2 and legacy oracle gating are unchanged.

Every qualification result must identify exact source and tool versions. Initial
fixtures are engineering evidence, not natural-repository performance or a
held-out result. New natural-corpus acceptance and maintainer label review are
separate unfinished requirements until concrete receipts exist.

Keep quality in its own required CI status when enabling enforcement. Use a
trusted pinned tool and trusted PR refs; do not swallow exit 2 or use
continue-on-error. Adding a workflow alone does not verify branch protection.
No version bump, tag, release or family repin is part of this feature branch.
