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
| [#500](https://github.com/taipei49314/checkwash/issues/500) `--task` at the root | A base miss at the root is an engine error when the base tree holds, compared with case ignored, a file, symlink or submodule at a prefix of the task path, or the path itself in another case. The comparison is on text, so on a case-sensitive checkout an untracked `task.md` beside a committed `TASK.md` is refused too. A task file the base does not hold at all is still read from the working tree, now with one stderr line: a CI step that names a task file the base never had still lets each change supply its own contract; so does a task path that names a base submodule exactly, when the head puts a file there. Inferred: other spellings a file system treats as the same file are not compared, such as Unicode normalization (NFC against NFD on macOS), names a file system's own case table joins but Unicode case folding keeps apart (`ı` against `I`, if NTFS's table maps them) and, on Windows, trailing dots or spaces, 8.3 short names and alternate data streams. `doctor`'s root lookup now gives up after 5 seconds per query (about 10 seconds from a subdirectory); when its first query times out, `doctor` reports on `--repo` as given with no message. |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
