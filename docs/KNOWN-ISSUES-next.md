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
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS tautologies | An assertion on literals alone, and an equality or inclusive bound with one operand on both sides, read as TAUTOLOGY. Truthy spellings of a self-comparison (`assert.ok(x === x)`), a subject of literals and builtins (`expect(String(1)).toBe("1")`), a name bound to a literal, `undefined`, `NaN` and `Infinity` as subjects, and self-comparison in `toBeCloseTo`, `toContain` or `within` still read at their old rung. A tautology in a catch adds no always-pass proof to #431's. The reachability half of #429 (`return;` or `if (false)` before an assertion) is not in this change. [Details](js-reachability.md). |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
