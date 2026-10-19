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
| [#434](https://github.com/taipei49314/checkwash/issues/434) Python assertions paired by subject | An old assertion now pairs first with a new one on the same subject, written out or through one plain local binding, so a precondition above a rewritten `==` no longer blocks; `match=` added to a bare `pytest.raises` is no finding. A new oracle that checks another subject against another expectation still blocks, as on [#457](https://github.com/taipei49314/checkwash/issues/457)'s real commit: take a reviewed exemption for such a rewrite. An expectation moved into a local in the same edit (`expected = 20.0`) still reads as `ASSERT_SUBSTITUTED`. A membership assert whose needle is not a literal (`f"{n}/{n} cases blocked" in out`) checks the needle, not `out`, so a count guard written above it still takes the old `"7/7 cases blocked" in out` and blocks, as on the dogfooded commit behind THREATMODEL row 85. A name bound any other way (a parameter, `global`, a tuple, a loop target, an annotation) or read in a nested function is taken as written. `approx(x)` -> `approx(x, abs=...)` still reads as new slack, and two approx checks in one test still pair in span order. [Details](assertion-coverage.md). |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
