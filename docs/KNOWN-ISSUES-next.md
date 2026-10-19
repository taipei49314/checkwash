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
| [#496](https://github.com/taipei49314/checkwash/issues/496) Python always-passing handler assertions | A broad handler in a Python test or conftest whose every assertion is proved to always pass now swallows the assertion its `try` guards, and is reported under its first line followed by `[always-passing assertion]`. The proof reads `assert` statements over literals, and `assertTrue`, `assertFalse`, `assertIsNone`, `assertIsNotNone`, `assertEqual` and `assertNotEqual` with literal operands in a `unittest.TestCase` method; anything else keeps the old exemption. Still passing: a name bound to a literal (`ok = True; assert ok`), an assertion on the caught error that cannot fail (`assert error`), other always-true shapes (`assert (x, "msg")`), a TestCase base reached only through a base imported from another module or a same-file mixin with no TestCase base, other `assert*` methods and third-party or mock assertions, and an assertion the handler never reaches (`if False: assert value() == 1`, or one after `return`). Adding an always-passing assertion to a handler that already swallows reports the new text. Still to measure: the standard and D-088 sets, in the combined sweep; if a block found there is false, #496 reopens. [Details](../DECISIONS.md) (D-163). |

[v0.8.0 known issues](KNOWN-ISSUES-v0.8.0.md) · [JS/TS reachability and tautologies](js-reachability.md)
