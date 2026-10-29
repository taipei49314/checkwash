# Embedding checkwash in another tool

This page is for tools that run checkwash and read its findings: pull-request
reviewers, CI reporters, dashboards. The contract itself is the
[machine findings contract](stability.md#machine-findings-contract-findings_version--ir_version)
in the stability page. [`findings.schema.json`](findings.schema.json) is its
machine-readable form: a JSON Schema (draft 2020-12) for
`checkwash_findings_version` 2.

## Run it and read the result

```bash
checkwash check BASE...HEAD --format json
```

For a pull request, `BASE...HEAD` compares the head with its merge base, so
commits that landed on the base branch meanwhile are not in the diff.
`BASE..HEAD` compares the two trees directly (SPEC §9).

| exit status | meaning | standard output |
|---|---|---|
| 0 | pass | the findings document |
| 1 | block | the findings document |
| 2 | usage, input or engine error | not a findings document; the reason is on standard error |

Exit 2 does not mean "no findings". With `--emit-ir`, exit 0 comes with the
IR instead. Treat standard output that does not parse, or that does not carry
`checkwash_findings_version` 2, as an error whatever the exit status. On exit
2 standard output is empty, except that from the next release most size
refusals print `{"unread": [...]}`, naming the side over the limit that
stopped the run (the [unreleased changes](#unreleased-changes-on-main) list
the exceptions).

- Standard output is UTF-8 bytes whatever the locale (SPEC §8). Decode it as
  UTF-8. Python's `subprocess.run(..., text=True)` decodes with the locale's
  encoding unless Python runs in UTF-8 mode, and on Windows that can garble or
  reject non-ASCII paths and evidence; pass `encoding="utf-8"` instead.
- Keep standard error. Some facts appear only there: an exemption whose key
  checkwash no longer accepts
  (`checkwash: <ledger>: ignored exemption: <key>: <reason>`), and, up to
  v0.8.0, a side over the source size limit that no detector read; the next
  release also lists most of those under `unread`
  ([unreleased changes](#unreleased-changes-on-main)). Assertion-coverage gaps
  are there too, and in `--coverage-report FILE` and SARIF. An expired exemption is
  dropped without a message; `checkwash doctor` counts it.
- Configuration and exemptions are read from the base side of the range, so a
  pull request cannot exempt itself.
- The blocking threshold is the base side's `gate.fail_on`, `high` by default.
  Pass `--fail-on` yourself if your tool needs to know it, because the
  document does not record it.

## IR payloads (0.10.0)

The findings envelope stays version2; `--emit-ir` is a separate IR3 document.
Select the decoder from the payload's `version`, never the package string.
An IR3 decoder requires the `globals.policy_shadows` proof map, even if empty,
and validates the fixed paths, digest and transition kind in stability.md.
An IR2-only consumer must refuse IR3, while a historical reader keeps IR2 as
IR2 with no shadow-proof assertion. Do not insert an empty map, relabel old
documents or reserialize old receipts to make them look current. Config and
exemptions remain BASE-side; fixture HEAD context never grants authority.

## Check the document

- Require `checkwash_findings_version == 2` and refuse any other value. Since
  v0.3.0 the number changes when a key is removed, renamed or changes meaning,
  or when a required key is added, and only in a minor release.
- Ignore keys you do not know. A release can add an optional key without a
  new number, and an optional key can be absent. The schema allows unknown
  keys for that reason; checkwash's own tests reject any key it emits that the
  schema does not declare.
- To validate, use any draft 2020-12 validator. The schema is published after
  v0.8.0 and ships in no package. Its keys and fields are the same in every
  release since v0.3.0, so the copy on `main` describes the documents of
  v0.3.0 to v0.8.0; from the next release on, take it from the tag you run.

## What each field is for

| field | rely on it for | do not |
|---|---|---|
| `verdict` | checkwash's decision under the effective `fail_on` | recompute it from `summary` |
| `allowlisted` | knowing an exemption covers the finding; such a finding never blocks | expect it to be left out: it stays in `findings` and in `summary` |
| `summary` | counts of all findings by severity | read it as the number of blocking findings |
| `severity` | the four values `info`, `warn`, `high`, `critical` | expect a detector to block on its own: detectors report `warn` and gating moves it |
| `rule` | a frozen id: never renamed or reused | assume the list is complete; new ids appear without a version change |
| `escalators`, `deescalators`, `shape` | the labels gating attached, and a TEST_DISABLED event's kind | treat the label sets as closed, or read every escalator as a raise: GUARDRAIL_CREATED stays at `warn` |
| `message` | showing to people | parse it; the wording changes in any release |
| `unit` | the test: a Python qualified name, with `#N` when several same-named definitions remain, `<suite>`, or a JavaScript test title; null for a file | split it on `.`, `::` or `/`; a JavaScript title can contain any of them |
| `fingerprint` | the finding's identity, compared for equality | parse it; see below |
| `before.span`, `after.span` | locating the evidence: `[start, end)` in Unicode code points, after a UTF-8 byte order mark is removed, bytes that are not UTF-8 become U+FFFD, and CRLF and CR become LF; `[0, 0]` means no location | use them as byte or UTF-16 offsets, or assume they index `path`: an assertion inherited from a conftest fixture or a helper module keeps its span in that file |
| order of `findings` | a deterministic order within one version | expect the same order from another version |

## SARIF

`--format sarif` is a separate SARIF 2.1.0 projection of the same findings.
The schema and `checkwash_findings_version` do not cover it. It leaves out
allowlisted findings, and its results carry the fingerprint in
`partialFingerprints` under `checkwash/v1` or, for content-bound keys,
`checkwash/v2`. When a fingerprint moves, a code-scanning tool can see a new alert.
See [machine interfaces and SARIF](remediation-upgrade.md#machine-interfaces-and-sarif).

## Fingerprints

A fingerprint is the key an exemption records (`checkwash allow`). Compare it
for equality and nothing else: its unit part can contain `/`, and its last
part has more than one form.

The document carries no fingerprint version: `checkwash_findings_version`
does not change when keys move, and the `v2:` inside some keys names a key
format, not a version to compare. The stability page promises that a recorded
exemption keeps matching within one minor release line; a minor release can
move fingerprints in any namespace, and its `DECISIONS.md` entry and release
notes name them ([fingerprint stability](stability.md#fingerprint-stability),
D-151). v0.5.0 and v0.6.0 listed their moves in release
entries (D-063, D-092). v0.7.0 did not, and its release notes do not mention
them; its round entries record them (below). Before v0.5.0, patch releases also
moved some keys without saying so: reading their code, v0.3.4
(CI_WORKFLOW_TOUCHED gaining a reason), v0.4.1 and v0.4.2 (JavaScript test
removals and assertions the earlier scan misread). There has been no patch
release since v0.5.0.

When the fingerprint of a finding moves, an exemption recorded for the old key
no longer applies. The finding is gated as if it had never been exempted, and
it can block. When a whole key format is retired, checkwash says so on
standard error, `checkwash allow` refuses the old key, and `checkwash doctor`
warns. A key that changed for any other reason matches nothing, with no
message. If you store fingerprints, re-run each reviewed change with the new
version, review it again and store the new key; the
[upgrade notes](remediation-upgrade.md#reviewed-exemptions) give the steps.

## Version ranges

- **In CI, pin exactly,** for example `checkwash==0.8.0`, and upgrade on
  purpose. Detector coverage grows in every release, so a new version can
  block a diff the old one passed.
- **A package that reads the document but stores no fingerprints** can
  require the oldest release it was tested with, for example
  `checkwash>=0.8`, with no upper bound, and check
  `checkwash_findings_version` at run time. A breaking change to the document
  changes that number.
- **A tool that stores fingerprints** (exemptions, baselines, alert tracking,
  de-duplication across runs) should stay below the next minor, for example
  `checkwash>=0.8,<0.9`, and re-review stored keys at each minor upgrade.

## Upgrade notes

### v0.10.0 to v0.11.0

0.11 is not released. These are the changes on the 0.11 candidate branch (D-189); a build
from main before that release reports `checkwash_version` `0.10.0`.

- **The document and the IR did not change:** findings version 2, IR version
  3, the same keys, finding fields, rule ids and fingerprints. `check`
  computes its verdict as before.
- **The Stop hook's `reason`** (`--format hook-json`, `decision: block`) is
  for Claude, and its wording changed. It still names the number of blocking
  findings and the first one, then tells Claude to fix the production code or
  report the finding to the user. After an ASSERT_WEAKENED or ASSERT_REMOVED
  finding's message it now quotes the assertion's source text, as
  ` (before: <text>; after: <text>)` or ` (before: <text>)` (D-191); the
  finding's `message` in the document is unchanged. It no longer contains a
  `checkwash allow` command, a fingerprint or the next-session sentence. A
  tool that took the fingerprint from the reason should take it from
  `--format json`.
- **A block verdict can carry no `decision`.** With `--hook-input stdin`, a
  stop whose hook input has `stop_hook_active` exactly `true`, with the same
  blocking set this hook last blocked on in the session, prints a
  `systemMessage` for the user and no `decision`. Every other block, and the
  size block (#456), still prints `decision: block`; the exit status is 0 as
  before. A tool that read the verdict from `decision` should run
  `--format json` instead. The set is recorded in
  `<git-dir>/checkwash/sessions/` as `<sha256(session_id)>.stop`.
- **A new hook command,** `checkwash hook pre-tool-use`, the managed Claude
  Code PreToolUse handler. It reads the hook input on stdin (at most
  8,000,000 bytes, waiting at most 10 seconds), takes `--repo` and ignores
  every other argument, and always exits 0. It prints exactly one JSON
  object, ASCII-escaped with sorted keys: `{"hookSpecificOutput":
  {"hookEventName": "PreToolUse", "permissionDecision": "ask",
  "permissionDecisionReason": "..."}}` when the proposed edit weakens a test,
  or could not be analysed because a side is over the source size limit or,
  under `on_engine_error = "block"`, because of an engine error or the
  30-second deadline; a `systemMessage` for such an unanalysed edit under any
  other `on_engine_error`; and `{}` otherwise. The reason is for people, like
  `message`. Unprintable and bidi characters in it are escaped, and a
  weakening reason names at most three findings in at most 1,200 characters,
  quoting their assertions as the Stop reason does where they fit, with no
  fingerprint. The output is not a findings document and has no version
  number.
- **`hook install --agent claude-code`** writes `.claude/settings.local.json`
  by default and adds the PreToolUse handler there; `--shared` writes
  `.claude/settings.json`, with no PreToolUse handler. A script that ran the
  command without a flag for shared settings must pass `--shared`. With
  neither flag, a repository whose shared settings already hold the managed
  Stop or SessionStart handler makes the install exit 2.

### v0.7.0 to v0.8.0

- **The document did not change:** the same keys, finding fields, version 2,
  rule ids, escalator labels and `shape` values (D-140).
- **Exit codes** of `--format json` did not change. `--format hook-json`, the
  Claude Code Stop hook format, did: an engine error now exits 0 with a
  `systemMessage` (D-134).
- **Fingerprints:** no change to an existing finding's key was recorded
  (D-140). That rests on the fixtures and each round's tests, not on a sweep of
  real history. New findings have keys of their own (D-136, D-137, D-138).
- **Verdicts:** new checks can block (#422, #431, #432), some runs that exited
  2 now give a verdict (D-131 to D-135, D-139), and a run from a subdirectory
  reads the repository root (#416).

A tool that reads the document, and does not store fingerprints, works with
v0.8.0 unchanged. A `<0.8` upper bound written for v0.7.0 shut v0.8.0 out
without need.

### v0.6.0 to v0.7.0

The document did not change. These round entries in `DECISIONS.md` record
moved fingerprints of existing findings, which the v0.7.0 release notes do not
mention: D-097 (CI_WORKFLOW_TOUCHED reasons); D-100 (a skip raised in a test
body became TEST_DISABLED); D-102, D-103 and D-104 (findings that changed
rule); and D-102, D-112, D-115 and D-117 (removed tests whose recorded
assertions changed). D-118 (AVA and tap) records no moved key in its own
fingerprint section, but its sweep of five JavaScript histories found 39
records where only a fingerprint or a message changed. Apart from D-118's
sweep, the list comes from the entries, not from real history. Some Git input
failures that used to pass exit 2 instead
([known issues](KNOWN-ISSUES-v0.7.0.md)).

### Unreleased changes on main

These ship in the next release, which D-146 says cannot be a patch release. A build from main
reports `checkwash_version` `0.8.0`, so a tool cannot tell it from the release
by that field.

- **The finding fields have not changed.** One optional top-level key and
  one escalator label are new (below).
- **Assertion-level fingerprints (D-146, #421).** ASSERT_WEAKENED,
  ASSERT_SUBSTITUTED, ASSERT_REMOVED, TOLERANCE_LOOSENED,
  EXPECTED_VALUE_CHANGED, EXPECTED_VALUE_DERIVED,
  EXPECTATION_DEFINITION_CHANGED, SUBJECT_NORMALIZED and SUBJECT_INPUT_CHANGED
  get content-bound keys, `rule/path/unit/v2:` and a 64-character digest.
  Their old keys are retired. Findings of one rule in one unit now sort by key,
  so their order can change, and SARIF `partialFingerprints` for these rules
  move from `checkwash/v1` to `checkwash/v2`.
- **TEST_DISABLED fingerprints (D-169, #512).** Every TEST_DISABLED finding
  gets a content-bound key of the same form, `TEST_DISABLED/path/unit/v2:`
  and a 64-character digest, a file-level focus under the unit `<file>`. Its
  old keys are retired, its findings in one unit now sort by key, and its
  SARIF `partialFingerprints` move to `checkwash/v2`. Every rule other than
  these ten keeps its key format.
- **Same-named test functions (D-144, #424).** A def that a later one replaces
  is no longer a unit, and the units that remain are renumbered, so findings
  keyed by them get new keys, with no message.
- **Python tests that never run (D-166, #499).** A def or class under a
  branch checkwash reads as dead is no longer a unit. A finding keyed by it
  goes, and a later unit of the same name can take a lower `name#N`, which
  gives its findings new keys, with no message.
- **Removed JavaScript tests (D-148, #429).** By reading the code, a removed
  JS/TS test whose callback held an assertion it never reaches now gets a new
  TEST_DISABLED key. D-148 records no key change; D-151 corrects it.
- **A new escalator label,** `PROD_CHANGE_NOT_EVIDENCE` (D-161, #473). E1
  used to print `NO_PROD_CHANGE_IN_DIFF` whenever a blocking finding's own
  evidence did not reach a production change. It now prints
  `PROD_CHANGE_NOT_EVIDENCE` when the diff changes a production-role file that
  is not inert. Severity, verdict and fingerprint are unchanged.
  `OPAQUE_PROD_CHANGE_NOT_EVIDENCE` (D-141, #419), which builds of main
  between #464 and the change that turned #419's refusal off printed, is not
  printed in v0.9.0 (D-171).
- **New findings,** among them: a known assertion replaced by a unittest call
  whose operands checkwash cannot bind (D-143, `strength_drop` 999), helpers
  reached through `self` (D-145, D-149), JS/TS assertions that can never fail
  or that the callback never reaches (D-147, D-148), and `collection.rebound`
  (D-144).
- **Verdicts:** some diffs that passed on v0.8.0 now block (D-144, D-145).
- **Exit codes** of `--format json` have not changed. In
  `--format hook-json`, a size refusal of a change in the diff that decides
  the verdict, when that change's head or worktree side is over the size
  limit, now exits 0 with `decision: block` instead of the non-blocking
  `systemMessage` (D-150, #456).
- **A size refusal names its side on standard output** (D-168, #454). It
  still exits 2, but `--format json` now prints `{"unread": [...]}` instead of
  nothing: one entry, with the `path`, `side`, `size` and `limit` of the side
  the refusal names, as below. It is not a findings document: it has no
  `checkwash_findings_version`, `findings` or `verdict`, so the version check
  above treats it as the error it is. A root manifest, config, exemption list
  or task file over the limit at the base, with a range a symlinked pytest
  configuration's target over the limit that no detector must read, and every
  other engine error still print nothing; so do `--emit-ir`, term and SARIF.
- **A new optional top-level key,** `unread` (#454). It lists the changed
  sides over the 1,000,000-byte source limit that checkwash set aside unread,
  one object per side with `path`, `side`, `size` and `limit`, and it is
  omitted when there are none. A change listed there was not analyzed, so a
  `pass` says nothing about it, and a tool that reads only `findings` will
  not see it. A validator that rejects unknown keys meets `unread` only on a
  run that has one. SARIF names each such side in a tool execution
  notification, not a result. `checkwash_findings_version` stays 2.


## Sweep summaries

`checkwash sweep HEAD --limit 200` writes a batch summary, not a findings
document. It has no `checkwash_findings_version`; do not validate it with
`findings.schema.json` or infer a per-commit pass from the CLI's exit 0.
Existing summary fields and exit behavior stay unchanged. `engine_errors`
counts commits whose analysis raised an exception; those commits are excluded
from `commits_analysed` and its block-rate denominator. A malformed base
configuration or exemption ledger retains its existing fallback behavior;
its diagnostic is not a successful policy validation.

An optional `commit_diagnostics` array is emitted only when nonempty. Consumers
should ignore unknown optional fields. Summaries without a diagnostic retain
their existing JSON bytes.

Each event has a full `commit` SHA, `phase`, `kind` and display `message`.
`parent` is present only after that parent was successfully read. Phases are
`read_commit`, `read_changes`, `load_config`, `load_allowlist`,
`read_manifests` and `analyze`. Kinds are:

- `config_parse_error`: base configuration could not be parsed; defaults
  remain in effect.
- `config_warning`: a base configuration value was rejected or ignored.
- `allow_parse_error`: base exemption ledger could not be parsed; no
  exemptions from it are active.
- `analysis_exception`: an exception counted in `engine_errors`, with
  `exception_type`; this commit was not added to `commits_analysed`.

Configuration events include their effective base-side `path`; value warnings
include a fixed setting `field`. Parse events include numeric `line` and
`column` only when the parser's original diagnostic provides that position.
No unknown parent or location is invented. Multiple events can concern one
commit; counting events does not count additional analyzed commits.

Messages are bounded fixed summaries, not the original free-form exception
or configuration value. Supplied values and unknown role names are omitted
because they can contain credentials, and arbitrary exception text is not
copied or formatted. A safe simple exception type name is retained; an unsafe
or excessive type name is represented by its `Exception` base category.
JSON escaping protects control characters. This output does not claim to
retain raw error detail; reproduce the named commit separately when further
investigation is needed. The existing special skip for an oversized root
lockfile remains separate from counted analysis exceptions.

The array adds observations only. It does not change findings, fingerprints,
policy fallback, thresholds, exclusions, counters or exit status. Strict
batch-summary validators must allow this optional field when adopting the
version that adds it.
