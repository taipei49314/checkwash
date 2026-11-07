# Release history

Releases with a summary or a release document in this directory, newest
first. Up to v0.10.0 the summaries are the ones the front-page
[README](../../README.md) carried for each release, with the same text and
link targets; from v0.11.0 they are written here. The README
has the current install commands and Action pin, and the
[advertised-release manifest](../../release/advertised.toml) records the
version, commit and download bytes behind them. A new publication record
starts from the [publication record template](publication-record-template.md).

## v0.12.0

Release candidate, prepared in the release pull request; the publication
record follows once the public files are verified.

**v0.12.0 refuses repair evidence to weakened, removed and skipped tests,
reads `unittest.mock.ANY` as the tautology it is, and points the release tag
at the Action commit the README recommends.** In a Python test or conftest, a
weakened, removed, skipped or loosened assertion, a broad `except`, a
stand-in for the code under test and a normalized or changed subject take
no repair evidence, and in a JS/TS test the loosening shapes take none, so
each blocks beside any production change unless something other than
repair evidence holds it, labelled `REPAIR_EVIDENCE_REFUSED` (D-199). An
expected value rewritten into `ANY` is a weakening, a single test's skip
earns the compatibility credit only when it provably runs somewhere, and
`assertEqual` rewritten as `assertCountEqual` drops order (D-201). From
v0.12.0 the tag points at the release's Action commit, and the README
installs the CLI only from PyPI and the pyz (D-200).
[Release evidence and known limits](v0.12.0-public-launch.md).

Known issues: [v0.12.0](../KNOWN-ISSUES-v0.12.0.md).

## v0.11.0

Published 2026-11-04; its public files are verified in the
[publication record](v0.11.0-publication-verification.md).

**v0.11.0 asks before a Claude Code edit weakens a Python test, stops counting
a proven failure relay as a swallow, and lets `doctor` accept the release's
own Action commit.** A local hook install, now the default, adds a
PreToolUse ask on five weakening rules, and a Stop block reports the finding
instead of offering an exemption (D-189). A broad `except` that relays a
failure to an awaited asyncio future is not counted as added (D-190). A
`pytest.raises` test folded into a literal `parametrize` table can keep its
credit, while parametrize cells that never reach the test as written earn
none (D-192), and a moved Python test pays only where the repository's own
pytest configuration collects it (D-193). #419 closes as a documented
residual (D-191). The README recommends v0.11.0's Action commit,
`v0.11.0^2^1`, not the commit the tag points to (D-194); from v0.12.0 the tag
points at the release's Action commit (D-200).
[Publication evidence](v0.11.0-publication-verification.md) ·
[Release evidence and known limits](v0.11.0-public-launch.md).

Known issues: [v0.11.0](../KNOWN-ISSUES-v0.11.0.md).

## v0.10.0

**v0.10.0 binds policy changes to the reviewed BASE and asks for source-bound
proof before a moved test oracle earns credit.** A newly winning `.checkwash`
config or allowance is compared with its BASE `.greenwash` predecessor, so a
change cannot approve its own relaxation; relative `--task` addresses resolve
from `--repo`; and moving assertion text, keeping assertion mass or keeping a
test name no longer proves the same oracle. The IR contract is now version 3;
the findings envelope stays at version 2.
[Publication evidence](v0.10.0-publication-verification.md) ·
[Release evidence and known limits](v0.10.0-public-launch.md).
A pass does not prove correctness; retain exit 2 and diagnostics as analysis
errors. With `--format hook-json` (the Claude Code Stop hook) an engine error
exits 0 with a "not analysed" message. The recommended Action is pinned to
the same v0.10.0 release.

**v0.10.0 compares a newly winning `.checkwash` policy with its BASE
predecessor and credits a moved oracle only with source-bound proof.**
Callers of `--emit-ir` read IR version 3, which adds `policy_shadows`; the
findings JSON stays at version 2. [v0.10.0 evidence and limits](v0.10.0-public-launch.md)

Known issues: [v0.10.0](../KNOWN-ISSUES-v0.10.0.md).

## v0.9.0

**v0.9.0 makes assertion-level exemptions content-bound
([#421](https://github.com/taipei49314/checkwash/issues/421)).** Through
v0.8.0, an exemption for one rewrite of an assertion also allowed every later
rewrite of the same line. Nine assertion-level rules now key a finding by the
old and the new assertion as well, TEST_DISABLED keys one by what the change
disabled ([#512](https://github.com/taipei49314/checkwash/issues/512)), and
their old keys stop matching: re-review and re-record those entries. [Assertion-level notes](../remediation-upgrade.md#assertion-level-rules-next-minor-421)

Records: [release guide](v0.9.0-public-launch.md) ·
[publication record](v0.9.0-publication-verification.md) ·
[issue closeout](v0.9.0-issue-closeout.md) ·
[known issues](../KNOWN-ISSUES-v0.9.0.md).

## v0.8.0

Records: [release evidence and limits](v0.8.0-public-launch.md) ·
[publication record](v0.8.0-publication-verification.md) ·
[known issues](../KNOWN-ISSUES-v0.8.0.md).

## v0.7.0

Records: [release evidence and limits](v0.7.0-public-launch.md) ·
[publication record](v0.7.0-publication-verification.md) ·
[known issues](../KNOWN-ISSUES-v0.7.0.md).

## v0.6.0

**v0.6.0 works through the reports and rulings that followed (#196–#261).**
JS/TS assertions keep their meaning across Jest, chai, Vitest and node:test,
and the runner a file's imports name decides whether a moved test still runs
and what a focus stops. Hand-rolled tolerances in both frontends, pytest
selectors under explicit targets, skip guards in a body, a setup or a conftest
hook, every `pytestmark` spelling and a CI config the reader cannot read now
reach the detectors. Some existing findings now carry a different fingerprint,
so allowlist entries for those shapes must be re-recorded; the JSON shape is
unchanged. [v0.6.0 evidence and limits](v0.6.0-public-launch.md)

## v0.5.0

**v0.5.0 closes a round of red-team reports (#172–#181).** A skip in a
fixture or setup the test runs, a selector over edited tests, a package
manifest's test command, Jest's `__tests__/` layout, JS block-level and
imperative skips, JS module mocks, hand-rolled JS tolerances, chai assertions
and CI control flow that stops a runner now reach the detectors; #173, #180
and #181 are closed in part. Some existing findings now carry a different fingerprint,
so allowlist entries for those shapes must be re-recorded; the JSON shape is
unchanged. [v0.5.0 evidence and limits](v0.5.0-public-launch.md)

## v0.4.2

**v0.4.2 strengthens JS/TS assertion evidence.** Test callbacks own their
assertions; changing a scalar expected value or loosening positive
`toBeCloseTo` precision reaches the existing detectors. Equivalent scalar
spellings remain equivalent across subject checks. This is bounded syntax
support, not general JS/TS analysis. [v0.4.2 evidence and limits](v0.4.2-public-launch.md)

## v0.4.1

**v0.4.1 repairs Node assertion recognition ([#164](https://github.com/taipei49314/checkwash/issues/164))**
and covers Node test-file names, bounded import aliases and lexical shadows.
Coverage warnings expose known assertion candidates the scanner cannot represent;
they do not prove complete JS/TS coverage. The same assertion contract checks
the source, wheel and zipapp. [v0.4.1 evidence and limits](v0.4.1-public-launch.md)

## v0.4.0

**v0.4.0 extends detection of runtime suppression, collection changes,
expectation rewrites and substituted subjects, and recognizes more table refactors.** The proofs retain
input identity, execution context and conservative handling of unknown code.
[Release evidence and remaining limits](v0.4.0-public-launch.md)

Records: [issue acceptance inventory](v0.4.0-issue-acceptance.md) ·
[pause checkpoint](v0.4.0-pause-checkpoint.md).

## v0.3.4

Records: [release guide](v0.3.4-public-launch.md).

## v0.3.3

Records: [release guide](v0.3.3-public-launch.md).

## v0.3.0

**v0.3.0 replaces five file-wide exemption rules with content-bound ones.**
In v0.2.13 those rules could reuse a recorded approval for a later change to
the same path; v0.3.0 retires their path-only keys. The [upgrade notes](../remediation-upgrade.md)
describe the content-bound replacement, retired keys, and installation fixes.

Records: [release guide](v0.3.0-public-launch.md).

## v0.2.13

Records: [release guide](v0.2.13-public-launch.md).

## v0.2.12

Records: [release guide](v0.2.12-public-launch.md) ·
[installed-asset qualification](v0.2.12-qualification/SUMMARY.md).

## v0.1.13

Records: [draft release notes, superseded](v0.1.13-candidate.md).
