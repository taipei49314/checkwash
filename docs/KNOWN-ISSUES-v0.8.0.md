# Known issues for v0.8.0

v0.8.0 is `main` at `cdd74e0`, the scope the maintainer fixed on 2026-10-15.
The acceptance sweeps of its rounds and the corpus sweep had not run when it
was prepared: `NOT_RUN：工作機規則（POLICY work-machine-local），the owner chose to release first and run them on the pool after publication`.
Unless a row cites a run, the false-positive cost of each change and the
number of v0.7.0 errors it recovers are unmeasured. Residuals below were
found by reading the code and the pull requests' reviews; where a row says
"inferred", nothing executed it.

## New in v0.8.0, or newly reachable

| Scope | Known limit and what it means for you |
| --- | --- |
| [#456](https://github.com/taipei49314/checkwash/issues/456) Stop hook size refusal | A changed file that a detector must read (the test itself, any `.py` module or any file with no extension, tracked or untracked and not ignored) and that is over 1,000,000 bytes stops analysis. Under `--format hook-json` that is the non-blocking "not analysed" message with exit 0 (#414), so an agent whose test edit would block can pad that file, or add such a file beside it, and stop. v0.7.0 exited 2 there, which blocks the stop. Every other format exits 2, and the required CI check still judges the committed change. Read every "not analysed" message as a check that did not run, not as a pass. Open for a ruling. |
| #414 hook-json engine errors | The same holds for any engine error in the Stop hook, for example an untracked, non-ignored directory symlink or one that pytest's collection can reach. This is the cost of the ruling not to trap the agent on errors it cannot fix; the hook is an author-side check and the required CI check, which runs in range mode, is the gate. |
| [#454](https://github.com/taipei49314/checkwash/issues/454) unread sides on stderr only | A pass can include a changed file over the limit that checkwash did not read. Only stderr names it. `--format json`, SARIF, the term report on stdout, the hook-json payload and the Action's step summary do not, and the exit code is that of a full pass. The Action writes stderr to the job log only. The skip of an oversized root `poetry.lock` or `uv.lock` is also stderr only. Keep stderr with every result. Open for a ruling. |
| [#455](https://github.com/taipei49314/checkwash/issues/455) oversized extensionless files | checkwash reads no byte of an oversized side, so it cannot rule out a shell shebang. Every changed file with no extension over the limit, including a `README`, a `LICENSE` or an `.envrc`, stops the run with exit 2 (or the hook-json message). A suffixed file whose shell shebang is only on an oversized side, such as `ci/run.txt`, is set aside unread instead of being judged as a runner script. Inferred: on runs that reach the runtime-provider pass's shebang phase, an unchanged file without a dot in its name over the limit may also refuse. Open for a ruling. |
| #415 other size residuals | A refusal for a change with two unread sides names the first one, not necessarily the side that must be read. Aggregate budget refusals and `read_config_many` do not name the side yet. A root `pyproject.toml` or `requirements*.txt` over the limit at the base still stops every run with exit 2, naming it. |
| #416 subdirectory runs | From a subdirectory, a `--task` file that the base tree does not hold at the mapped path is an engine error; name an untracked task file from the root. With `--repo` naming an in-repository directory symlink and `--task` outside it, the mapped path can miss the base file, which from a subdirectory is also an engine error. `allow` names the root ledger under Git's spelling of the root (absolute, forward slashes on Windows). A Cygwin-style Git that prints `/c/...` makes `check` from a subdirectory exit 2; `allow` and `doctor` keep `--repo`. `hook install` still writes under `--repo` as given, so after `hook install --local` in a subdirectory `doctor` reads the root's `.claude/`, does not see those settings and, with nothing else installed, reports "no checkwash installation found". Whether Claude Code runs the Stop hook from the session's directory is unverified. The wrong-blob false pass reported in #416 was not reproduced. |
| `--task` fallback at the root | Pre-existing and unchanged (#453's merge comment). At the root, when the base tree has no file at the task path, checkwash opens `--task` as given and the operating system follows symlinks. A base-side symlink on the task path, or `--repo` reached through a symlink to the root, can therefore let the working-tree copy, which the change controls, supply the contract. Name a task file committed as a regular file in the base, and pass `--repo` without symlinks. |
| `doctor` root lookup | `doctor` finds the repository root with the general Git timeout of 60 seconds per query, not its own 5-second queries. A Git that hangs can stall `doctor` for that long before it falls back to `--repo` as given. |
| `doctor` Action pin | v0.8.0's `doctor` accepts only the Action commit built into it, the prior release v0.7.0's `d647a65e`, which has the trust-boundary issue. A release cannot name its own commit, so a workflow pinned to the v0.8.0 Action, as the README will recommend after verification, is reported as "workflow analysis incomplete" with an unsupported SHA. This is a warning, not a failure. |
| #414 directory symlinks | An untracked, non-ignored directory symlink is still refused by the change-list read, naming it. The importer search still refuses a directory symlink outside hidden, `.venv` and `node_modules` trees. Windows junctions are not treated as symlinks. |
| #346 pytest configs | Working-tree mode does not read symlinked configs; they are still refused there, and when a root config is touched the collection-inventory pass can still refuse a nested config symlink. In a range check every symlinked config name is resolved up front, so an unsafe link fails closed even when dormant. Other symlinks, including a custom `-c` file name, are not covered. The psf/requests directory-symlink row may still exit 2. |
| #345 large and deep sources | The subject-replacement pass keeps its own 30,000-node limit. #389 reported that five aiohttp commits still exit 2 (two at the stand-in step guard, two at that node limit, one at a nonregular snapshot). A 1 MB file of ordinary statements took 4.263 s before and 9.788 s after the limit change, whole run to refusal (#389, run 38292837314). Deep string chains are rebuilt only for complete top-level `NAME = STRING (+ STRING)+` lines; any other deep shape still raises `RecursionError` and exits 2. A very deep binary expression used directly as an asserted subject keeps a null semantic result, so its meaning is not compared (#374, #384). |
| #422 exit-status reader | Read directly and in same-file callees only. Missed spellings include hook parameters with defaults or keyword-only ones, hooks bound by assignment or called through an instance, nested functions published with `global` or `nonlocal`, decorator, context-manager and annotation call routes, aliases of `sys.exit`, `pytest.exit`, `SystemExit` and `pytest.fixture`, `from os import *`, a negative `testsfailed` literal, several namespace-write spellings, and a rebound `os.fork`. A changed value on an existing exit marker adds no finding. Out of scope: `pytest_cmdline_main`, `pytest_runtestloop` and `pytest_collection` short-circuits, other callback registrations, plugin modules, exits in test or production code, `os.exec*`, computed names, `ctypes` and start-up files; the exit-5 recipe combined with a run that collects nothing. |
| #432 no-op replacement reader | Pinned silent: loops, `with` and `except` bodies, async hooks, hooks bound by assignment, class plugins, autouse fixtures, call-built or attribute-sourced replacements, computed names, `__dict__` writes, subclasses, `sys.modules` lookups and `addTypeEqualityFunc`. Also missed: a hookwrapper that restores `item.runtest` after its `yield`, a builtin callable as the replacement, a write inside a same-file helper, and a no-op `addFailure`. Inferred, and not read as a runtime control: a hook or replacement from another file (a hook the conftest imports, a module it names in `pytest_plugins`, a replacement it imports and assigns), a write followed by a `raise` that a handler catches (`try: raise X` / `except X: pass`), and the same swap written in a test module instead of a conftest. A no-op proof accepts a call, raise or assert that never runs. An unrelated edit to a top-level `if` can re-report an unchanged replacement. |
| #431 always-passing catch assertions | JS/TS only, and only `true`, `false` and `null` literal operands. Number and string literal equality, `toEqual(true)`, message arguments and self-comparison go to #429. The Python counterpart (`except Exception: assert True`) is open. The always-failing direction is pinned by a test only for Vitest `expect`. |
| Action boundary | The v0.8.0 Action closes the trust-boundary issue for a clean, dedicated hosted job. The interpreter, shell startup, runner image, PyPI build tooling and setup-python remain trusted, and an earlier step that ran pull-request code can compromise the job. The v0.6.0 and v0.7.0 Actions remain affected; re-pin them. A composite Action cannot stop a caller from choosing weaker inputs; protect the workflow file by review. |
| Sweeps and cost | Not run, as stated above. The new blocks of #422, #432 and #431, the verdicts that replace v0.7.0's errors, and the engine and Action cost of the release commit are unmeasured. The issues of those rounds stay open until the sweeps and their DECISIONS text land. |

## Open P1 reports this release does not address

| Issue | What passes today |
| --- | --- |
| [#306](https://github.com/taipei49314/checkwash/issues/306) | A helper method reached through `self`: weakening or deleting its assertion, or a skip in it, passes with zero findings. Ruled, not implemented. |
| [#418](https://github.com/taipei49314/checkwash/issues/418) | The Stop hook compares HEAD with the working tree only: work the agent commits during the session, and an allow entry or config it commits, are not analysed by the hook. Ruled (record the session base at `SessionStart`), not implemented. |
| [#419](https://github.com/taipei49314/checkwash/issues/419) | A no-op edit buys repair evidence: `+ 0` in the called function, or a comment edit in any non-Python production file, holds a weakened, removed or skipped assertion at warn, which passes at the default threshold. Ruled, not implemented; #448 only stops unread sides from earning evidence. |
| [#421](https://github.com/taipei49314/checkwash/issues/421) | An assertion-level exemption binds only the old line: one `allow` for a reviewed rewrite also passes any other rewrite of that line by the same rule until it expires. Ruled; moved to a later minor release on 2026-10-15. Keep expiries short and review entries. |
| [#424](https://github.com/taipei49314/checkwash/issues/424) | A later rebinding of a test's name (a second `def test_x`, `del test_x`, `test_x = None`) hides the test with zero findings. Ruled, not implemented. |
| [#428](https://github.com/taipei49314/checkwash/issues/428) | JS/TS `test.each`, `it.each` and `test.for` are never scanned: a weakened or deleted assertion, an edited row or a deleted table passes with zero findings. Ruled, not implemented. |
| [#429](https://github.com/taipei49314/checkwash/issues/429) | JS/TS `expect(x).toBe(x)`, an assertion under `if (false)`, or a `return;` before it passes with zero findings; Python blocks all three. Ruled, not implemented. |
| [#212](https://github.com/taipei49314/checkwash/issues/212) | No independently selected JS/TS history replay measures the false-positive cost of the JS/TS rounds. |

Other open reports include [#417](https://github.com/taipei49314/checkwash/issues/417)
(under Python 3.10 the pyz exits 1, the block code, with a traceback),
[#434](https://github.com/taipei49314/checkwash/issues/434) and its real-world
instance [#457](https://github.com/taipei49314/checkwash/issues/457) (a
precondition before a rewritten `==` blocks as `ASSERT_WEAKENED`),
[#420](https://github.com/taipei49314/checkwash/issues/420) (one-hop repair
evidence never applies to a top-level callee),
[#436](https://github.com/taipei49314/checkwash/issues/436) and
[#437](https://github.com/taipei49314/checkwash/issues/437) (`doctor`
reports FAIL right after install; `allow` accepts a past `--expires`), and
the missed cheat [#480](https://github.com/taipei49314/checkwash/issues/480)
(a TypeScript return annotation on a JS/TS arrow test callback, such as
`(ctx): void =>`, hides its context's assertions, and the coverage report
can still say `no_known_gaps`). The
[issue list](https://github.com/taipei49314/checkwash/issues) has every open
report.

The missed cheats [#423](https://github.com/taipei49314/checkwash/issues/423),
[#425](https://github.com/taipei49314/checkwash/issues/425),
[#426](https://github.com/taipei49314/checkwash/issues/426) and
[#433](https://github.com/taipei49314/checkwash/issues/433) are deferred
until after 1.0 ([#504](https://github.com/taipei49314/checkwash/issues/504)).
So is [#278](https://github.com/taipei49314/checkwash/issues/278), which
this page did not list at release: checkwash does not read pytest 9's
native `[tool.pytest]` table in `pyproject.toml`, so a new `pyproject.toml`
whose native table narrows collection, or a `-m` selector added to an
existing native table, passes with only `CI_WORKFLOW_TOUCHED` at warn
(#278's runs at `6e4f5ef`, before v0.8.0). Review changes to that table by
hand.

## Status of the v0.7.0 known issues

| v0.7.0 scope | In v0.8.0 |
| --- | --- |
| #363 synchronous JS/TS catch reader | Boundary unchanged. #449 narrows one exemption: a catch whose only assertions are proved always-passing no longer counts as inspecting the failure. |
| #357 imported-helper guards | Unchanged. |
| Git input failures | Partly fixed. A side over the limit that no detector reads is carried unread instead of refused, the root lockfile case is skipped, and every size refusal names path, side, size and limit (#448). Symlinked pytest configs in range checks and dormant nested configs no longer refuse (#442), and worktree directory symlinks are opaque (#447). Other changed nonregular paths and must-read sources over the limit still refuse. How many of the 54 added pass-to-error pairs are recovered is unmeasured. |
| Worktree snapshots | Unchanged: non-atomic reads and undetected change-and-revert. |
| Fixed JS/TS noise | Unchanged and not re-measured. |
| Cost | v0.7.0's figures do not describe v0.8.0, whose cost is unmeasured beyond the per-change runs the release guide cites. |
| #212 comparison and legacy integrity | Unchanged; #212 stays open. |
| #366 / #367 / #364 | Answered on 2026-10-14, still open, outside this scope. |
| T-528 A–D and historical materializer | T-528 closed as CANCELLED on 2026-10-14: A delivered with its six held-out candidates UNVERIFIED, B not started, C done, D cancelled. No held-out measurement exists. |
| Release and Action identity | The pre-tag parity failure no longer exists: candidate CI and published-source checks are separate (#373, D-130). The one-release Action lag ended on 2026-10-14; the README advances to the v0.8.0 Action after its publication checks pass. The v0.8.0 Action contains the trust-boundary fix (#372, #375). |

The maintainer authorized this release on 2026-10-15, approved the
maintainer text of its rounds as drafted, and chose to run the acceptance
sweeps after publication. That decision retains the limits above; it supplies
no new empirical result.

[Release evidence and limits](releases/v0.8.0-public-launch.md)
· [v0.7.0 known issues](KNOWN-ISSUES-v0.7.0.md)
· [Subject integrity](subject-integrity.md)
· [Catch boundary](js-catch-swallowing.md)
· [Action advisory](../SECURITY.md#known-issue-action-trust-boundary)
