# Known issues on main after v0.8.0

This page collects the known limits of changes merged into `main` after
v0.8.0. Nothing on it is released. When the next release is prepared, its
known-issues page takes these rows over, with what that release measured.

Residuals below were found by reading the code and the pull requests'
reviews. The acceptance sweeps of these changes have not run:
`NOT_RUN：工作機規則（POLICY work-machine-local），each sweep runs where the owner approves it`.
Their false-positive cost is unmeasured.

| Scope | Known limit and what it means for you |
| --- | --- |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS tautologies | An assertion on literals alone, and an equality or inclusive bound with one operand on both sides, read as TAUTOLOGY. Truthy spellings of a self-comparison (`assert.ok(x === x)`), a subject of literals and builtins (`expect(String(1)).toBe("1")`), a name bound to a literal, `undefined`, `NaN` and `Infinity` as subjects, and self-comparison in `toBeCloseTo`, `toContain` or `within` still read at their old rung. A tautology in a catch adds no always-pass proof to #431's. [Details](js-reachability.md). |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS reachability | An assertion after an unconditional `return` or `throw`, under a branch a literal-only folder decides dead, or behind `false &&`, is not the test's. A `return` in a loop, `do`, `try` or labeled body ends nothing after it; `break`, `continue`, `switch`, `for (... of [])` and `const` bindings are not read; and wherever the walk cannot prove a statement's end (a line break next to a template or regular expression, a typed function declaration, unpaired brackets), the assertions after it keep their reading. A test registered in dead code is outside this change. The walk refuses every text the shared token stream was found to misread, but one it misreads and no refusal notices can still make live code read as dead, which reports `ASSERT_REMOVED` ([#490](https://github.com/taipei49314/checkwash/issues/490)). [Details](js-reachability.md). |
| [#454](https://github.com/taipei49314/checkwash/issues/454) unread sides in the output | A changed side over the 1,000,000-byte limit that checkwash set aside unread is now listed under the optional `unread` key of `--format json`, as a SARIF notification and as a `!` line of the term report. A validator that rejects unknown keys meets `unread` only on a run that has one. Not listed: the readable side of a range-mode rename whose other side is over the limit, though that whole change was set aside; the skip of a root `poetry.lock` or `uv.lock` over the limit at the base, which stays a stderr note (when the diff also changes that lockfile, the change's sides over the limit are listed like any other); and the side a size refusal names, since that run gives no findings report ([#456](https://github.com/taipei49314/checkwash/issues/456) stays open for it, as (d)). The Stop hook's JSON and `--emit-ir` name no unread side. A worktree side's size is its size on disk, so a text file near the limit can be listed on a CRLF checkout and read on an LF one. [Details](stability.md#machine-findings-contract-findings_version--ir_version). |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
