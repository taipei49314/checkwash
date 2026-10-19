# Known issues on main after v0.8.0

This page collects the known limits of changes merged into `main` after
v0.8.0. Nothing on it is released. When the next release is prepared, its
known-issues page takes these rows over, with what that release measured.
A row marked *Existing* is a limit v0.8.0 already had that was documented
only after its release; the row says where it was found.

Residuals below were found by reading the code and the pull requests'
reviews, unless a row names another source. Unless a row says otherwise,
the acceptance sweeps of these changes have not run:
`NOT_RUN：工作機規則（POLICY work-machine-local），each sweep runs where the owner approves it`.
Their false-positive cost is unmeasured.

| Scope | Known limit and what it means for you |
| --- | --- |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS tautologies | An assertion on literals alone, and an equality or inclusive bound with one operand on both sides, read as TAUTOLOGY. Truthy spellings of a self-comparison (`assert.ok(x === x)`), a subject of literals and builtins (`expect(String(1)).toBe("1")`), a name bound to a literal, `undefined`, `NaN` and `Infinity` as subjects, and self-comparison in `toBeCloseTo`, `toContain` or `within` still read at their old rung. A tautology in a catch adds no always-pass proof to #431's. [Details](js-reachability.md). |
| [#429](https://github.com/taipei49314/checkwash/issues/429) JS/TS reachability | An assertion after an unconditional `return` or `throw`, under a branch a literal-only folder decides dead, or behind `false &&`, is not the test's. A `return` in a loop, `do`, `try` or labeled body ends nothing after it; `break`, `continue`, `switch`, `for (... of [])` and `const` bindings are not read; and wherever the walk cannot prove a statement's end (a line break next to a template or regular expression, a typed function declaration, unpaired brackets), the assertions after it keep their reading. A test registered in dead code is outside this change. The walk refuses every text the shared token stream was found to misread, but one it misreads and no refusal notices can still make live code read as dead, which reports `ASSERT_REMOVED` ([#490](https://github.com/taipei49314/checkwash/issues/490)). [Details](js-reachability.md). |
| [#468](https://github.com/taipei49314/checkwash/issues/468) expected-failure records a test runner reads | *Existing.* In undici's `test/web-platform-tests/expectation.json`, recording a regressed subtest as `success: false` or `flaky: true`, or marking its test file `skip: true`, passes with zero findings. Under 1,000,000 bytes the file has the `test` role, and over that size it is set aside unread (#415); either way no rule reads its content. By reading, undici's runner fails no run on a changed result today, so the edit hides the regression in the record, and `skip` stops the file from running. Review the diff of such a file by hand. No detector is scheduled (D-160). Source: the v0.8.0 acceptance sweep, whose JavaScript batch left this file unread in 10 undici commits (on LAPTOP-01AGNPJU under POLICY `checkwash-pju-sweep`, T-546). [Details](assertion-coverage.md#expected-failure-records-a-test-runner-reads). |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
