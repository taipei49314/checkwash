# Quality configuration review

The v0.3.4 package includes this limited quality preview, separate from
`checkwash check`. Packaging it does not establish natural-case acceptance,
production enforcement maturity or frozen legacy-byte parity. The
[release guide](releases/v0.3.4-public-launch.md) retains those limits.

`checkwash quality BASE...HEAD` reviews declared configuration requirements.
It does not execute repository code, inspect live branch rules, or verify that
CI actually ran the declared tools. No network access or external tool process
is used by the quality core. Development qualification runs pinned tools only
against trusted synthetic fixtures on existing hosted CI.

## Use

For draft generation, setup diagnostics and a separate PR status, follow the
[adoption guide](quality-adoption.md).

```text
checkwash quality init
checkwash quality doctor
checkwash quality profiles --details
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

This branch packages `coverage-7.16.0-q1`, `ruff-0.16.6-q1` and `mypy-2.3.1-q1`.
`quality profiles` is the authoritative inventory, including content digests.
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
- Ruff: qualified rule catalog, namespace-aware selection/ignore comparison,
  incompatible-rule resolution, bounded extend chains and nearest-config
  resolution per surviving source file. Preview settings, unqualified context,
  per-file overrides and gitignore-dependent scope remain incomplete.
- Mypy: global flags, the complete 13-flag strict expansion for the pinned
  version, explicit overrides of those flags, and nine default error codes.
  Inline directives, module overrides, other error codes and regex scope remain
  incomplete. Mypy has no qualified scope adapter in this preview.
- Configuration source inventory includes higher-priority candidate absence,
  selected source contents and declared version-source changes.

Deleting an explicitly selected configuration produces incomplete analysis:
the tool may fail to start, so defaults cannot be assumed. Auto discovery can
use a lower-priority source or qualified defaults; source candidates and their
absence are included in evidence. Inherited exclusions anchored in different
directories remain unsupported. Only literal relative file paths and literal
directory/** exclusions are qualified for coverage/Ruff scope comparisons.
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

The native qualification has 45 comparisons, including full Ruff selected-rule
sets, precedence across configuration formats, inherited and nested Ruff
configuration, coverage scope and mypy strict expansion. Packaged models include
the qualification fixture and result hashes. Provenance and the remaining
acceptance conditions are in [the qualification record](quality-qualification/README.md).

To try the packaged preview, install `checkwash==0.3.4`. The recommended
v0.3.3 test-oracle Action does not include `quality`; a CLI installation does
not update that Action. The preview's native/package checks and retained
T-255 comparison failure are identified separately in the release guide.

Keep quality in its own required CI status when enabling enforcement. Use a
trusted pinned tool and trusted PR refs; do not swallow exit 2 or use
continue-on-error. Adding a workflow alone does not verify branch protection.
The v0.3.4 publication is governed separately under estate T-332; it does
not assert completion of the quality design's acceptance conditions.
