# Known issues for 0.10.0

Status, 2026-10-28: limits of the published v0.10.0. The first three sections
come from the pre-release review of the 0.10 candidate; each was traced or
reproduced on actual LAPTOP-01AGNPJU / Windows / CPython 3.11.9
(HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL). The Publication section was found
when the published release was checked and by the review of the follow-up. Three other
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
  Git's tree. The working tree is listed before the link is refused, so in a
  tree that also holds a junction cycle or more than 200,000 paths the same
  refusal surfaces as the inventory error instead of this message; the
  outcome (exit 2, `not analysed`) is the same. Raised by a Grok review of
  #566 and verified by Claude.
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
- **A `pytest.raises` fold blocks.** Found after release, from an outside
  report on [#130](https://github.com/taipei49314/checkwash/issues/130#issuecomment-6531871133)
  (2026-10-30). The proof binds only top-level `assert` statements, so
  `with pytest.raises(...)` tests folded into a literal `parametrize` table,
  honest or not, lose their credit and block at high, where 0.9.0 passed
  them; a file that lost only raises tests without `match=` never reaches D5
  either. This is a conservative false block, not a missed cheat. 0.11 fixes
  it ([D-192](../DECISIONS.md)); on 0.10.0 an exemption in the base-side
  `allow.toml` is the way through.

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

## Publication

- **`doctor` and the v0.10.0 Action pin.** The published 0.10.0 `doctor`
  accepts only the Action commit built into it, v0.9.0's `d6eda4f6`. A release
  cannot name its own commit, so a workflow pinned to the v0.10.0 Action, as
  the README recommends after verification, is reported as "workflow analysis
  incomplete" with an unsupported SHA, and `doctor` exits 1. `doctor` from main
  accepts the v0.10.0 pin.
- **PyPI description.** The PyPI 0.10.0 page shows the README as built from
  the release commit: it still names v0.9.0 in its summary, install commands
  and Action pin. Its D-185 link is relative, so it does not resolve on PyPI,
  and its usage-guide link names a section the v0.9.0 guide does not have.
  PyPI keeps the first upload's description; use the GitHub README.
