# #414 hosted acceptance run: declaration

**Draft for the owner's approval. Nothing has run.** Owner ruling 2026-10-19,
R26 (option A): this declaration holds only #414's legs, the owner approves it
on its own, and it runs first, before the combined sweep. Owner ruling
2026-10-19, R25 (option A): #414's range-mode part is read from the v0.8.0 run
(see "Range mode" below).

## Beyond R26, for the owner's approval

R26, as recorded on #414, names the legs: on ubuntu, an in-tree
`python3 -m venv .venv` (with `lib64`) and a pnpm workspace, each in term and
hook-json mode, and an npm tree over 200,000 files; on windows, pnpm. This
declaration adds the following. The owner
approves or declines each on its own; a declined one is removed from the
driver and from this file before the pull request is opened.

1. A v0.7.0 control arm, and the **inconclusive** status it brings (see
   "What counts as accepted").
2. A third mode on main, **stop-hook**: the managed SessionStart and Stop
   pair (see "Scenario and commands").
3. main pinned at `0e60832a`, where the combined sweep plan named a487
   (`637222e8`) (see "Engines").
4. v0.8.0 rows, report only (the plan: "optionally also at v0.8.0").
5. The large npm tree from a generated package installed from a tarball
   (see "Legs").
6. In "Range mode", the earlier engine changes the v0.8.0 range also holds,
   beside R25's "six changes".

## Where it runs

- On GitHub-hosted runners, through `.github/workflows/acceptance-414.yml`
  and its driver `tools/acceptance_414.py` (standard library only; it never
  imports checkwash). They run on a draft pull request from
  `ci/acceptance-414-hosted` that is never merged. Opening that pull request
  starts the run, so it is opened only after this declaration is approved.
  Once the result is recorded on #414, the pull request is closed and the
  branch deleted, as for the #479 mutation checks (#485, #486).
- The job runs only for a pull request from a branch named
  `ci/acceptance-414-*` in this repository, and the workflow triggers only
  when the pull request changes the workflow or its driver. The file is never
  on `main`, so no ordinary pull request runs it.
- **Results are hosted CI, not the EC pool.** Nothing runs on a work machine:
  `NOT_RUN：工作機規則（POLICY work-machine-local），#414 rows run on hosted CI`.
  Rulings list item 18 (2026-10-18, approved) puts these rows on hosted CI,
  and adopts its lean that hosted results may close the issue.
- The pull request also gets the ordinary checks, none of which is part of
  this acceptance: every workflow with no `paths` filter (`checkwash`,
  `verdict gate`, `assertion qualification` with its candidate and
  recommended-Action jobs, and `quality qualification` with `qualify` and
  `action-smoke`); the `ci` matrix, because the pull request changes files
  other than Markdown; and `docs suite`, because it adds this Markdown file
  under `docs/`.

## Engines

| Name | Commit | Tree | Role |
|---|---|---|---|
| main | `0e60832a618653511f764ea7e44994dce92df558` | `ee4a31ef28ed68719e1a76977fe9df5d7d0118b6` | required: decides acceptance |
| v0.8.0 | `f02b5d8a07fa39ee1898881f66c571eb164cb11c` | `ada5d81cfa12cbabb6298715d67ebc7f67e9b27e` | report: the released fix (#447), recorded beside main |
| v0.7.0 | `d647a65e9734f2b6e57b528ea595b1507dc31094` | `14294c318beb7a90e8b6d8cc0d195d0ffea38ba2` | control: the code before the fix |

The driver checks each commit and tree in the run's own clone, checks it out
with `git worktree add --detach`, installs it with pip into its own virtual
environment on Python 3.12, and runs that environment's `checkwash` console
script. main and v0.8.0 both print `checkwash 0.8.0`; the receipt names the
commit. The combined sweep plan named a487 (`637222e8`). main has since gained
#505 (the hook-json size block, in `cli.py`), which the next release ships. By
reading, #505 changes no row here: the path-limit refusal is an `EngineError`,
not a `SourceOverLimit`.

## Legs

| Leg | Runner | Real setup, run in the scenario repository |
|---|---|---|
| ubuntu-venv | `ubuntu-latest` | `python3 -m venv .venv`, then `.venv/bin/python -m pip install --no-deps pytest==8.3.4 iniconfig==2.0.0 packaging==24.2 pluggy==1.5.0` |
| ubuntu-pnpm | `ubuntu-latest` | `npx --yes pnpm@9.15.0 install --no-frozen-lockfile` in a two-package workspace: `packages/web` depends on `packages/shared` as `workspace:*`; the root and `shared` depend on `semver@7.6.3` |
| ubuntu-npm-large | `ubuntu-latest` | `npm install --save-exact semver@7.6.3 big-tree-1.0.0.tgz`, where the tarball is a generated package of 201,002 files |
| windows-pnpm | `windows-latest` | the ubuntu-pnpm workspace and command |

Node, npm and Python are the runner's; the receipt records their versions.
The large tree's files come from a generated package, because no pinned set of
registry packages is known, by reading, to exceed 200,000 files. npm installs
it from a tarball: a `file:` directory would become a directory symlink,
which the walk lists and never enters. The row tests the path limit, which
depends only on the count and the walk order.

Not in this declaration: #416's macOS and symlink legs (R13: CI already
covers them); tox and nox environments, yarn, and macOS for #414; the
issue's fourth acceptance item, a test of a directory symlink in the
worktree inventory, which `tests/test_issue414_worktree_directory_symlinks.py`
has covered in CI since v0.8.0.

## Scenario and commands

The scenario of `tests/test_issue414_worktree_directory_symlinks.py`, on a real
tree:

1. A new repository holds `src/pkg/__init__.py` (`total()` returns `78.75`),
   `tests/test_total.py` (asserts `total() == 78.75`), a `.gitignore` listing
   `.venv/` or `node_modules/`, and the leg's project files.
2. The leg's real setup runs.
3. The driver checks that the setup is real: `.venv/lib64` is a directory
   symlink and `.venv/bin/python` exists (venv); `node_modules/semver`,
   `packages/shared/node_modules/semver` and `packages/web/node_modules/shared`
   are directory links, symlinks or junctions (pnpm); the tree holds more than
   200,000 entries, counted as the working-tree walk counts them, and
   `node_modules/.bin/semver` exists (npm-large).
4. Everything not ignored is committed, lockfiles included, so the only
   change is the next step's edit.
5. The edit: `total()` returns `round(78.75, 2)`. It is an honest production
   edit, expected to pass.

Then each engine runs from the repository root, with no range and no
`--repo`, as the hooks run it:

- **term**: `checkwash check --format term`, the pre-commit hook's entry.
- **hook-json**: `checkwash check --format hook-json`, the issue's command and
  the managed Stop handler of v0.7.0 and v0.8.0.
- **stop-hook**, main only: `checkwash hook session-start` with a SessionStart
  input on stdin, then `checkwash check --format hook-json --hook-input stdin`
  with a Stop input on stdin. This is the pair `checkwash hook install` writes
  on main (#418).

The driver sorts each run into one outcome:

- **pass** or **block** (a verdict): in term mode, exit 0 or 1 with
  `verdict=pass` or `verdict=block` and no engine-error line; in hook-json, exit
  0 with `{}` (a pass) or a block.
- **pass with a note**: hook-json, exit 0 with only a `systemMessage` that is
  the session note (#418), not a refusal. No row expects it. No commit is made
  during the session, so after a recorded SessionStart the Stop prints `{}` on
  a pass; a note ("no start was recorded ...") means the record was not found
  or not used, which the SessionStart call cannot show, because it exits 0
  whatever happens. It is a mismatch, and the summary quotes the note.
- **refusal**: an engine error the user is told about. In term mode that is
  exit 2 with the `checkwash engine error:` line. In hook-json it is exit 0
  with only a `systemMessage` that begins "checkwash: this change was not
  analysed".
- **silent exit 2**: hook-json before #414, which is exit 2 with nothing on
  stdout.
- **other**, or **timeout** (900 s).

## Expected results

By reading the three engines. In every row, main and v0.8.0 are expected to
agree.

| Leg | main and v0.8.0, every mode each runs | v0.7.0 (control) |
|---|---|---|
| ubuntu-venv | a verdict, expected pass | term: refusal, `strict snapshot inventory cannot follow directory symlinks`; hook-json: silent exit 2 |
| ubuntu-pnpm | a verdict, expected pass | the same as ubuntu-venv |
| windows-pnpm | a verdict, expected pass | no expectation; recorded |
| ubuntu-npm-large | refusal naming the path: `strict snapshot inventory exceeds the path limit of 200000 at node_modules/big-tree/`, on stderr in term mode (exit 2), and in the `systemMessage` with exit 0 in hook-json and stop-hook | term: refusal, `strict snapshot inventory exceeds the path limit`, naming no path; hook-json: silent exit 2 |

Why:

- **venv and pnpm on Linux.** `WorkingTreeSnapshot.list_paths` lists each
  directory symlink (`.venv/lib64`, pnpm's links) as an opaque directory and
  does not enter it (#447). The edit reaches the runtime-shadow pass, which
  lists the tree and then returns before it reads any source, because no other
  path provides `pkg`. pytest's default `norecursedirs` keeps `.venv` and
  `node_modules` out of collection. v0.7.0 raises at the first directory
  symlink.
- **pnpm on Windows.** pnpm normally links directories there with junctions
  (general knowledge, not checked here). `Path.is_symlink()` is False for a
  junction, so every engine walks through them and lists the linked files
  again under each link, as
  `docs/KNOWN-ISSUES-v0.8.0.md` says ("Windows junctions are not treated as
  symlinks"). The tree is small, so main and v0.8.0 give a verdict. Whether
  v0.7.0 refuses depends on whether pnpm made junctions or symlinks, so its
  rows have no expectation; the receipt records each link's kind.
- **stop-hook.** `hook session-start` records HEAD for the session. The Stop
  finds that record with no commit since, so the session's base is HEAD and
  main adds no session note: stdout is `{}` on a pass.
- **npm-large.** The limit is unchanged (#414 ruling, item 1). The walk counts
  every file, ignored ones included, and stops at entry 200,001, inside
  `node_modules/big-tree/`; by reading, that entry is
  `node_modules/big-tree/data/d199/f993.txt`. The check needs only the prefix.
  hook-json reports that engine error with exit 0 (#414 ruling, item 2), and
  the refusal names the path (item 3). v0.7.0 named no path and exited 2.

## What counts as accepted

Each leg gets one status:

- **accepted**: the setup checks hold, every main row matches its expected
  result, and on the three ubuntu legs every v0.7.0 row matches too.
- **inconclusive**: main matches but a v0.7.0 row on an ubuntu leg does not.
  The setup then did not reproduce #414, so main's result says nothing about
  the fix.
- **not accepted**: a main row does not match.
- **setup not reproduced**: a setup check fails.

The job is green only for **accepted**. v0.8.0 rows are reported and never
change the status. A block where a pass was expected still counts as a
verdict for #414, and the summary lists it. A pass with a note does not
match.

#414's real-setup acceptance is met when all four legs are accepted. With the
range-mode part below and the CI test above, #414 can then be closed, as item
18 allows for hosted results.

## Range mode (R25)

This run has no range-mode row. Under R25, #414's range-mode share comes from
the v0.8.0 acceptance sweep, which is accepted as it is. That sweep compared
v0.7.0 `d647a65` with v0.8.0 `f02b5d8` over 6,354 commits on 2026-10-15. It was
labelled a human-authorized local PJU run under EC POLICY
`checkwash-pju-sweep` (T-546), not the EC pool. The summaries are on
checkwash-lab `prep/acceptance-sweep-v080-20261016` at `954d802b`, under
`runs/acceptance-sweep-v080/20261016-pju/`. Its `combined/combined.json`
shows no verdict flip between pass and block in any batch. 30 commits moved
from a product error to an analysed pass (standard 2, targeted 3, javascript
25), and d088 had no move.

The run does not isolate #414's change. As R25 notes, it spans six changes
from #447 on: #447 (#414 itself), #448, #449, #450, #452 and #453. #447 also
changes `gitio/snapshot.py` and `opaque.py`, which range mode reaches. The
range also holds the earlier engine changes since v0.7.0: #374, #384, #386,
#439, #441 and #442, and the release, #458 (the version and `doctor.py`). The
pre447 and a447 arms are not run.

## Receipts and the record

Each leg uploads `acceptance-414-<leg>-attempt-<n>`, which holds:

- `receipt.json`: engines, tool versions, setup checks and links, the
  scenario's base commit, and every run's argv, stdin, exit, stdout, stderr,
  their sha256, outcome, expectation and match;
- `summary.md`, also shown in the job summary;
- `engines.json` and `tools.txt`;
- `rows/<engine>-<mode>.stdout` and `.stderr`, the raw bytes.

The record on #414 names the run id and attempt, the pull request's head
SHA, each leg's status, each `receipt.json` sha256 and the NOT_RUN line
above. A leg that is not accepted is reported to the owner as it is, and
nothing is rerun or changed without the owner.
