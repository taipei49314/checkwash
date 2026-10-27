# Known issues for 0.10.0

Status, 2026-10-27: candidate limits found by the pre-release review of the
0.10 candidate. Each was traced or reproduced on actual LAPTOP-01AGNPJU /
Windows / CPython 3.11.9 (HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL). Three other
review findings were fixed before release; they are listed in
[the release guide](releases/v0.10.0-public-launch.md). Earlier limits remain in
[KNOWN-ISSUES-v0.9.0](KNOWN-ISSUES-v0.9.0.md) and
[KNOWN-ISSUES-next](KNOWN-ISSUES-next.md); the disclosed 0.10 refactor costs
stay in [the D-185 dispositions](oracle-context-dispositions-0.10.0.md) and
[the D-187 cost record](d176-cost-disposition-0.10.0.md).

## Worktree and Stop hook

- **Linked pytest configs are refused in worktree mode.** A pytest config that
  is a symbolic link, including a link checked out as a regular placeholder
  file under `core.symlinks=false` (the Windows default), makes a worktree or
  Stop check refuse with `worktree pytest config is not a regular source`
  (exit 2, hook `not analysed`). Use a repository-owned regular config, or
  rely on the committed-range required check, which follows the link from
  Git's tree.
- **On-disk spelling that differs from Git's.** On a case-insensitive file
  system, when a directory holding a pytest config is spelled differently on
  disk than in the index (for example `Tests/` on disk, `tests/` in Git), or
  after a case-only directory rename in the working tree, a worktree check
  can refuse with a captured-inventory error instead of analysing. The
  committed range is unaffected.

## Oracle-context credit

- **Plain-class certificate can replace a module-level proof.** When the
  closed plain-class certificate applies to a file, it replaces the ordinary
  module-level oracle context for that file's units. A legitimate relocation
  that the ordinary proof would credit can then be withheld and block. This
  is a conservative false block in a narrow domain, not a missed cheat.
- **Same-record renames use the destination path on both sides.** For a test
  file renamed in one Git rename record, the relocation proof reads package
  initializers and relative imports at the destination path for both sides.
  A cheat that relies on a different package initializer at the old path is
  not distinguished. 0.9.0 credited relocations by text alone, so this is not
  a regression, but the proof is narrower than its description.

## TASK and quality

- **TASK block shape.** A column-0 list item inside a TASK contract block ends
  the block without a diagnostic, so fields after it are ignored. Write list
  items indented under their field. The TASK input is opt-in (`--task`); the
  managed hook and Action do not pass one.
- **`quality init` advice for unresolved INI contexts.** When an INI candidate
  such as `setup.cfg` contains a `[DEFAULT]` section, `quality init` reports
  `CONTEXT_UNRESOLVED: INI DEFAULT inheritance is not modeled` correctly but
  advises adding configuration that already exists. The exit code and state
  are correct; only the advice text is misleading.
