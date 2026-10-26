# Bounded UX repair candidate, 2026-10-26

This is a review candidate based on `1ffe283d7d947fecc426dea99323b0a2620a9482`,
the existing unpublished v0.9.1 source. Public upgrade comparisons also retain
v0.9.0, `d6eda4f695fabb8e7d138f7a87b099d2028f0294`. There is no version bump,
merge or publication instruction. The r65 v0.9.1 publication pause remains.

## Named repair slices

Each implementation commit addresses one named defect. Existing golden fixture
labels, protected policies and the machine finding/fingerprint definitions are
unchanged.

| Slice | Behavior and boundary |
|---|---|
| Registered worktree gitlinks | Only an exact index stage-0 mode160000 directory is treated as a pointer entry. Ordinary directories, unregistered nested repositories, symlink replacements and regular-file deletion evidence retain strict handling. Checked-out context remains available. |
| Quality CRLF-only sources | Policy, allow and tracked version comparisons use the same CRLF boundary as source digests. Absence stays distinct from empty bytes; comments, order, lone CR and real policy/version changes remain significant. |
| Quality junctions on Python 3.11 | Directory traversal recognizes the exact mount-point reparse tag without depending on Path.is_junction. Other reparse tags are not classified as junctions. |
| Quality usage errors | JSON and SARIF requests receive parseable error output with exit 2. Init/doctor JSON retains the separate advisory setup envelope; ordinary review errors retain the review envelope. |
| Wrong-ledger quality keys | `checkwash allow` rejects exact currently known quality rule IDs before writing, naming `.checkwash/quality-allow.toml` and target_id. It does not add a quality writer or change either ledger's approval policy. |
| Unknown namespace diagnostics | Unknown keys remain stored and eligible under existing rules for newer-engine compatibility. Writer/check/doctor explain that this version emits no matching finding. Doctor distinguishes eligibility from actual use; diagnostic display quotes control characters. |
| Human decoration | Demo/report-owned symbols, separators and truncation markers use readable ASCII in legacy streams. Source evidence remains visibly escaped by the existing writer; machine UTF-8 bytes are not rewritten. |
| Sweep pytest configuration input | The sweep analyzer receives the paired pytest configuration context already used by range review. This addresses logical pytest configuration aliases without changing sweep output fields or exit behavior. |

## Validation and limits

Development receipts on LAPTOP-01AGNPJU / Windows / Python 3.11.9 include
red-before/green-after regression controls and independent source review.
They are marked `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. Raw commands, exits,
stdout/stderr and source hashes are preserved in the task evidence package.
Development tests on a shared integration tree are not final-source release
qualification. Final candidate tests and self-dogfood are recorded separately.

Native Git controls preserve adjacent real findings and checked-out context.
Quality controls cover valid existing exemptions, real content changes and
native inside/outside junctions. Output controls preserve source evidence,
future namespaces and the existing schema/exit distinctions. Existing fixture
labels were not changed. The setup usage test now validates its requested
machine format while preserving the original exit-2 rejection requirement.

An early Action regression run retained seven failures: six selected the WSL
bash launcher instead of existing Git Bash; one detected a source-copy mismatch
while the integration tree changed. These failures remain in the evidence.
A fixed candidate and explicit process-local Git Bash path are needed for the
final run. No host PATH, service, security or runner setting is changed.

Native macOS/Linux, other Python versions, cross-platform equality, artifact
qualification and formal release checks need their own evidence. No historical
sweep, model/adjudication batch, cohort, benchmark labels or downstream pin is
changed by this work.

## Reproduced issues needing separate decisions

- D2 assertion/body move credit can excuse changed decorator/local expectation
  context even with oracle_freeze. A direct literal-unroll variant is already
  blocked, while legitimate moves/unroll controls pass. Seventy-two static CLI
  controls on the two old versions show identical results, including a
  worktree/range difference for cross-file parameter changes. Changing D2/D5,
  E2 ordering or identity/equivalence requires protected policy review and a
  minor release; this candidate does not implement those proposals.
- Adding `.checkwash/config.toml` can shadow stricter `.greenwash` policy while
  the creation classifier compares against defaults. Directory precedence and
  the comparison baseline require a contract decision.
- Relative `--task` paths resolve from cwd rather than the documented repo
  base. A repo-owned task supplied by absolute path is the positive control.
  Changing the resolution base needs its own CLI compatibility decision.
- Quality report-to-enforce edits are still critical guardrail changes in
  `check`, while quality review uses the old report policy. A second quality
  exemption and managed-hook upgrade approval are separate trust-policy work.
- TASK front matter still has its restricted parser: BOM, trailing comments,
  quoted booleans and flow lists are not equivalent to canonical input. Parser
  probes do not establish runtime exploit outcomes. Expanding accepted syntax
  or activating previously ignored policy requires a contract decision.
- Sweep config/allow diagnostics and exception commit identities are still
  incomplete. The input-context slice does not repair those diagnostics.
- Successful quality explain/profiles formatting and init draft guidance,
  main-reader junction diagnostics and CRLF rename/fingerprint compatibility
  remain separate follow-up slices.

The bounded candidate may fit a patch release after full compatibility and
acceptance checks. A complete rename/oracle contract repair belongs to a
separately authorized minor candidate. Neither conclusion authorizes bumping,
merging, tagging or publishing a version.
