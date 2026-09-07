# Upgrade notes for v0.3.0

**Released as v0.3.0 on 2026-09-07.** These notes describe what changed from
v0.2.13. The recommended Action and doctor's supported pin advance to v0.2.13 in
this release and to v0.3.0 in the next (one-release trust lag); v0.3.1
(2026-09-07) advanced them to v0.3.0. Installing the public v0.2.13 artifact
does not install these fixes.

## Reviewed exemptions

In v0.2.13, five rules use a fingerprint derived from the rule and path alone:
GUARDRAIL_TOUCHED, CI_WORKFLOW_TOUCHED, TEST_FILE_UNPARSEABLE, SCOPE_DRIFT,
and SNAPSHOT_CODE_COCHANGE. For those rules, a recorded exemption can cover
another modification to the same path. Default expiry is 90 days and the cap
is 180 days; expiry does not make the scope narrower. Snapshot co-change is
normally warn, so its exemption-reuse effect matters when warn is blocking.

The candidate migrates these rules to content-bound identities. A key ends in
`/v2:` followed by the complete 64-character SHA256 digest. It binds both
analyzed snapshots, their existence, the path/change kind, rename information,
and rule-specific context. CRLF is normalized to LF; other bytes and whitespace
are retained. CI weakening evidence, parser state, effective scope, and related
production changes are included where that rule depends on them. Merely
changing commit SHAs does not change the key.

Legacy keys for these rules remain visible records but cannot suppress a
finding. `allow` rejects new legacy keys; doctor counts retired and invalid
entries separately, and check reports ignored keys on stderr. Other rule
identities keep their existing scheme. There is no automatic upgrade: the old
reason does not contain the original content pair needed to reconstruct an
approval.

To accept a specific reviewed change:

1. Run the candidate on the intended review range and inspect the complete
   diff, finding, and reason for accepting it. Copy the full fingerprint from
   JSON or the report's copyable command, not a shortened digest.
2. On a separate branch from the intended base, record the approval:

   ```bash
   checkwash allow "<full-fingerprint-from-the-reviewed-report>" --reason "<why this exact change is acceptable>"
   ```

3. Review and merge that ledger-only change through the repository's normal
   approval process. The ledger path printed by the command is authoritative;
   `.checkwash/allow.toml` takes precedence over `.greenwash/allow.toml` when
   both contain that file.
4. Update the original change onto the new base and rerun checkwash. If the
   target snapshots and relevant context are unchanged, the approval matches.
   A different content pair needs another review. An exemption added only on
   the head of the current diff does not approve that diff.

Removing an old entry is a ledger modification and remains critical. Use a
separate, explicitly reviewed cleanup change before subsequent governance
edits. A content-bound key stored in the very ledger it would approve changes
that ledger's own before digest; it is not a way to approve its own cleanup.
Do not add another path-wide key or disable the gate to get cleanup through.

An active exemption removes the finding from gating even at `--fail-on info`.
JSON retains it with `allowlisted: true`; the terminal's visible count and
SARIF omit suppressed findings. Neither the visible count nor a lower severity
is a record of all originally detected findings.

## Machine interfaces and SARIF

The candidate advances IR_VERSION and FINDINGS_VERSION to 2. Existing
`checkwash_*` envelope keys, exit codes, and severity policy are retained.
IR file records can carry a `change_evidence` object with before/after digests
and rename metadata; detectors that need that identity reject missing or
invalid evidence. Consumers should gate on the schema version and treat
fingerprints as opaque strings, not assume a twelve-character final segment.

The optional boolean `FileIR.native_assertion_context_unchanged` defaults to
false. It carries the narrow source proof for [numeric assertion restoration](numeric-restoration.md):
only one non-artifact file and one native assertion may change, with all
surrounding source unchanged. Missing proof retains the original finding.

In-process callers that analyze [root assertion helpers](root-assertion-helpers.md)
must provide complete, strict `root_reader` and `root_searcher` snapshots.
The CLI and sweep supply these adapters. Old `head_reader`/`head_searcher`
callbacks are not proof that an importer or package is absent. Without the
new callbacks, modifying a previously transparent root helper is an engine
error; new root extraction receives no credit. Consumers must adapt before
repinning their in-process engine.

SARIF remains 2.1.0. Migrated identities use `partialFingerprints.checkwash/v2`;
other identities retain `checkwash/v1`. Source location comes from the analyzed
head snapshot, including an inherited assertion's helper file. When no precise
head location exists, the result is file-level with evidence text and side in
properties. A projected root-helper assertion instead points to its concrete
caller, where the expected argument appears. A base offset is not projected onto the current file and line 1
is not invented. Columns and raw character offsets are omitted.

## Local installation and doctor

`checkwash hook install --agent claude-code --local` binds an isolated Python
runtime to the current package or zipapp, in `.claude/settings.local.json`.
Reinstall after moving that runtime or zipapp. The shared settings form requires
an installed portable `checkwash` CLI on Claude's PATH; it does not copy a
machine-specific absolute path into shared configuration.

Generated handlers require Claude Code's command/args exec-form support,
qualified here with **2.1.260**. On that runtime, a clean Stop completed and a
blocked Stop repeatedly received denial. At the test's ten-turn limit Claude
still ended its process; a local hook is not a merge gate. Configuration
installation, direct handler execution, a real Stop event, and CI enforcement
are separate checks. The installer preserves custom hooks and does not create
a Git ignore rule.

Doctor reads local and shared Stop configuration. A local-only installation
should be reported as configured locally but missing CI, exit 1. Doctor does
not run Claude or inspect all global/managed settings. For workflows, it now
distinguishes untracked files, index/worktree differences, unsupported refs,
and unsupported syntax while keeping its strict accepted workflow set. A
reviewed `git add` can resolve an index problem; a commit is not required just
for recognition. Doctor cannot verify live branch protection.

`hook install --agent pre-commit` still emits a YAML template. Its leading
comments explain how to save/merge the configuration and install/run pre-commit;
the command does not itself write that file or install Git hooks.

## Release completion

A fixed wheel or zipapp does not update an existing hook, installed CLI, or
Action pin. Under the current one-release trust lag, publish and qualify the
fixed minor release first, then advance the recommended Action and doctor's
supported pin in the next release. Do not call the recommended CI path fixed
while it still executes an older engine (the current recommendation is
v0.2.12). The legacy ledger can become active again on
an old engine, so downgrading to v0.2.13 is not a safe default rollback.

The maintainer's SPEC/THREATMODEL/DECISIONS review, release slot, published
artifact parity, actual Action qualification, and final human acceptance are
still required. These notes do not announce a release or replace those checks.
