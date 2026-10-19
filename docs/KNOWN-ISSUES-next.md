# Known issues on main after v0.8.0

This page collects the known limits of changes merged into `main` after
v0.8.0. Nothing on it is released. When the next release is prepared, its
known-issues page takes these rows over, with what that release measured.

Residuals below were found by reading the code and the pull requests'
reviews, unless a row names another source. Unless a row says otherwise,
the acceptance sweeps of these changes have not run:
`NOT_RUN：工作機規則（POLICY work-machine-local），each sweep runs where the owner approves it`.
Their false-positive cost is unmeasured.

| Scope | Known limit and what it means for you |
| --- | --- |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS tautologies | An assertion on literals alone, and an equality or inclusive bound with one operand on both sides, read as TAUTOLOGY. Truthy spellings of a self-comparison (`assert.ok(x === x)`), a subject of literals and builtins (`expect(String(1)).toBe("1")`), a name bound to a literal, `undefined`, `NaN` and `Infinity` as subjects, and self-comparison in `toBeCloseTo`, `toContain` or `within` still read at their old rung. A tautology in a catch adds no always-pass proof to #431's. [Details](js-reachability.md). |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS reachability | An assertion after an unconditional `return` or `throw`, under a branch a literal-only folder decides dead, or behind `false &&`, is not the test's. A `return` in a loop, `do`, `try` or labeled body ends nothing after it; `break`, `continue`, `switch`, `for (... of [])` and `const` bindings are not read; and wherever the walk cannot prove a statement's end (a line break next to a template or regular expression, a typed function declaration, unpaired brackets), the assertions after it keep their reading. A test registered in dead code is outside this change. The walk refuses every text the shared token stream was found to misread, but one it misreads and no refusal notices can still make live code read as dead, which reports `ASSERT_REMOVED` ([#490](https://github.com/taipei49314/checkwash/issues/490)). [Details](js-reachability.md). |
| [#488](https://github.com/taipei49314/checkwash/issues/488) helper-method skips | A known false block, which the next release is the first to carry: v0.8.0 does not contain #306's change. A test that calls, through `self`, a helper method holding a guarded skip whose guard is not a compat gate (SPEC §5 D6) now reads as not live (D2), as it already did with that skip in its body, its setup or a helper function. So when a change merges or moves tests into ones that call such a helper, the old tests can lose their move or restructure credit, and their `TEST_DISABLED` findings then go to high unless repair evidence or another de-escalator holds them at warn, and at high they block even when the change only adds coverage. #306's acceptance sweep, which ran in part (2026-10-17, human-authorized local PJU, NOT EC pool; D-145), found one such block in the commits it judged, scrapy `fada8be1db`; how often this happens is not known. The block stays until a later change removes it. Meanwhile you can exempt these findings by fingerprint only through an `allow.toml` entry already on the base side; one added in the blocked change itself shows as `EXEMPTION_ADDED` and does not lift the block. Further cases are recorded on #488. |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
