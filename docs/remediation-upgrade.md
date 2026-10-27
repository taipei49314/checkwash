# Upgrade notes for v0.3.0

**Released as v0.3.0 on 2026-09-07.** These notes describe what changed from
v0.2.13. The recommended Action and doctor's supported pin advance to v0.2.13 in
this release and to v0.3.0 in the next (one-release trust lag); v0.3.1
(2026-09-07) advanced them to v0.3.0 and v0.3.2 (2026-09-07) to v0.3.1, both
on the v0.3.0 engine. Installing the public v0.2.13 artifact does not
install these fixes.

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

### Assertion-level rules (next minor, #421)

Through v0.8.0, ASSERT_WEAKENED, ASSERT_SUBSTITUTED, ASSERT_REMOVED,
TOLERANCE_LOOSENED, EXPECTED_VALUE_CHANGED, EXPECTED_VALUE_DERIVED,
EXPECTATION_DEFINITION_CHANGED, SUBJECT_NORMALIZED and SUBJECT_INPUT_CHANGED
key a finding by its rule, path, unit and the old assertion's text only. While
the base still holds that line, an exemption recorded for one rewrite of it
also allows every other rewrite the same rule reports, and identical copies of
one assertion share a key.

The next minor release gives these rules content-bound keys as well:
`rule/path/unit/v2:` followed by the complete 64-character SHA256 digest. The
key binds the old and the new assertion text, what kind of change it is, which
of several identical copies changed, and the rule's context: a tolerance's old
and new values, or the definition an unchanged expectation now reads.
Reformatting outside string literals and moving the line keep the key.

Legacy keys of these rules are retired as the five above were: kept as
records, never honoured, refused by `allow`, and reported by doctor and check.
To keep an approval, re-run the reviewed change with the new version and record
its new key with the four steps above. TEST_DISABLED moves in the same minor
(below). EXPECTED_VALUE_HARDCODED, CONFTEST_PATCHES_PROD and
TEST_PATCHES_SUBJECT keep their legacy keys for now. IR_VERSION and
FINDINGS_VERSION stay 2.

### TEST_DISABLED (next minor, #512)

Through v0.8.0, TEST_DISABLED keyed a finding by its rule, path, unit and a
fixed text: the marker's name, which for an imperative `pytest.skip()` leaves
out its `if` guard; `guard:<marker>` for a guard made always true and for one
removed alike; `parametrize` whatever rows went; a removed unit's assertions,
a JS/TS one only through its matcher's `(`; and one name for any focus added
to a file. So an exemption recorded for one skip, guard change or deleted row
also allowed later, different changes to the same unit: an unguarded skip
after a guarded one was approved, the other guard event, or the deletion of
any other row.

The next minor gives TEST_DISABLED the same key form, `rule/path/unit/v2:`
and the complete 64-character digest (a file-level focus under the unit
`<file>`). The key binds what kind of change it is and what changed: an
added marker's text and its guard, the guard before and after, which rows
were deleted or newly disabled and the live counts, a removed unit's
complete assertions, or a file-level focus's spelling (`describe.only`,
`fdescribe` or an `only` option, not the block it is on). Reformatting
outside string literals and moving the lines keep the key. Which markers
pair, and how many findings a change gives, do not change.

Legacy TEST_DISABLED keys are retired the same way: kept as records, never
honoured, refused by `allow` (exit 2, naming #512), and reported by doctor
and check. Re-run each reviewed change with the new version and record its
new key with the four steps above.

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
other identities retain `checkwash/v1`. From the next minor (#421), the nine
assertion-level rules above are migrated identities too, and so is
TEST_DISABLED (#512). Source location comes from the analyzed
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

**Which window the Stop hook checks (#418).** Since #418 the installer writes
two handlers: the Stop handler runs `check --format hook-json --hook-input
stdin`, and a SessionStart handler in a group of its own runs `hook
session-start`, which records HEAD once per session under
`<git-dir>/checkwash/sessions/` and prints nothing. At each Stop, the working
tree against HEAD decides the verdict, as before, but policy (config,
allowlist, `--task`, manifests) is read from the commit the session started
from. An exemption or config change the agent commits during a session
therefore applies from the next session; `/clear` starts one. On a pass,
findings the session's commits hold are named in a non-blocking
`systemMessage` and left to the required check; a block leaves them to a
later Stop. When the Stop handler reads hook input but finds no usable record
(no SessionStart handler, a resumed session, which is never recorded, a record
pruned after 30 days, or HEAD with no history in common with it), a pass says
the session's commits were not analysed. A Stop handler installed before #418
reads no hook input, so it keeps the old window and says nothing; doctor notes
it. Run `checkwash hook install --agent claude-code` again, with `--local` for
`.claude/settings.local.json`, to install both handlers; the installer
replaces the earlier managed Stop handler.

Shared settings (`.claude/settings.json`) run the `checkwash` on each
teammate's PATH. A checkwash older than #418 rejects `--hook-input` as an
unknown argument and exits 2, which Claude Code reads as a blocked stop, so
upgrade every teammate's CLI before committing the reinstalled settings.

A record under `.git` is still writable by the agent, and the agent can run
`hook session-start` itself, so the required CI check remains the gate.

Doctor reads local and shared Stop configuration. A local-only installation
should be reported as configured locally but missing CI, exit 1. Doctor does
not run Claude or inspect all global/managed settings. For workflows, it now
distinguishes untracked files, index/worktree differences, unsupported refs,
and unsupported syntax while keeping its strict accepted workflow set. A
reviewed `git add` can resolve an index problem; a commit is not required just
for recognition. Doctor cannot verify live branch protection.

Since v0.8.0
([#416](https://github.com/taipei49314/checkwash/issues/416)): inside a Git
repository, doctor and the installed handler's `check` run from the
repository root, wherever they are started. The handler therefore analyses
the whole repository from any directory, and doctor reads the root's
`.github/workflows` and `.claude/`. `hook install` is different: it writes
`.claude/settings*.json` under `--repo` exactly as given. After
`hook install --local` in a subdirectory, doctor from that subdirectory names
the root on stderr and does not see those settings, which are not in the
root's `.claude/`. With nothing else installed it reports "no checkwash gate
found" (up to v0.8.0, "no checkwash installation found") rather than
"configured locally but not in CI", exit 1 either way. Outside Git, doctor and `allow` use the directory as given, as
before. When Git names a subdirectory but its root cannot be resolved, they
also use the directory as given and say why in one line on stderr.

`hook install --agent pre-commit` still emits a YAML template. Its leading
comments explain how to save/merge the configuration and install/run pre-commit;
the command does not itself write that file or install Git hooks.

## Release completion

A fixed wheel or zipapp does not update an existing hook, installed CLI, or
Action pin. Under the current one-release trust lag, publish and qualify the
fixed minor release first, then advance the recommended Action and doctor's
supported pin in the next release. Do not call the recommended CI path fixed
while it still executes an older engine (when these notes were written the
recommendation was v0.2.12; the [README](../README.md#use-it-in-ci) states
the current pin). The legacy ledger can become active again on
an old engine, so downgrading to v0.2.13 is not a safe default rollback.

The maintainer's SPEC/THREATMODEL/DECISIONS review, release slot, published
artifact parity, actual Action qualification, and final human acceptance are
still required. These notes do not announce a release or replace those checks.


## Policy-shadow migration in 0.10.0: IR3, findings2

The earlier version2 migration above is historical and remains unchanged.
The 0.10.0 policy-shadow contract adds a required IR3 proof slot at
`globals.policy_shadows`, present even when empty, and keeps findings2.
Upgrade IR decoders and current-source artifact validators explicitly;
keep old IR2 evidence and its pinned reader unchanged. A missing IR3 slot
refuses rather than being treated as no shadow. Re-review the moved shadow
GUARDRAIL approvals; there is no mechanical approval translation. This contract was implemented under the pre-1.0 repair instruction;
release checks and any publication approval remain separate. Stop for
Nelson's decision before 1.0.
