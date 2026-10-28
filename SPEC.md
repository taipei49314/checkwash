# greenwash SPEC — frozen contracts

This file is the single source of truth for rule IDs, the assertion strength
lattice, alignment parameters, severity philosophy, and determinism rules.
Changing anything here requires a version bump of the affected schema and a
full fixture re-run. Coding agents have **read-only** authority over this file
and over `tests/gates/**`; changes are made by the human maintainer only.

Spec version: 3 (IR payload `version: 3` with required `globals.policy_shadows`, introduced by the 0.10.0 policy-shadow contract D-177; findings envelope `checkwash_findings_version: 2` retained from v0.3.0). Historical IR2 payloads remain IR2 and carry no newly inferred shadow proof.

## 1. Analysis unit

greenwash analyses a *diff* (a pair of git trees: `base` and `head`), never a
single code state. The head side — including the whole working tree in hook
mode — is treated as attacker-controlled data. Configuration and exemptions
are always read from the **base** side.

In the managed Claude Code Stop hook (`check --format hook-json --hook-input
stdin`, #418) the verdict's diff is HEAD against the working tree, and the base
side that configuration and exemptions are read from is the session base: the
commit the session started from, as the SessionStart hook recorded it, or its
merge base with HEAD (§9). That record lives
under `.git`, which the agent can write, so it narrows the hook's window and is
not a reviewed base; only a required CI check in range mode reads one.

In the managed Claude Code PreToolUse hook (`hook pre-tool-use`, 0.11, D-189)
the diff is one change that has not been made yet: the path's current
working-tree bytes (none for a new file, an addition) against the bytes the
proposed Edit or Write would leave there (§9). Both sides are working-tree
data, attacker-controlled as above, except that HEAD's copy is the before side
when the working copy does not parse and HEAD's does. Configuration and
exemptions are read from the session base when a usable record exists, and
otherwise from HEAD, by the Stop hook's rule; no `--task` is read (§4c). The
same record chooses the commit this hook reads policy from; the hook is an author-side check,
and the required CI check in range mode remains the gate.

## 2. File roles

Paths are normalized to forward slashes before matching. Default role globs
(overridable in `.checkwash/config.toml`, or the legacy `.greenwash/config.toml`; read from base side):

| role      | default globs |
|-----------|---------------|
| conftest  | `**/conftest.py` |
| test      | `tests/**`, `**/test_*.py`, `**/*_test.py` |
| guardrail | `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.claude/**`, `.greenwash/**`, `.checkwash/**` |
| ci        | `.github/workflows/**`, `.github/actions/**/action.yml`, `.github/actions/**/action.yaml`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini`, `setup.cfg`, `**/pyproject.toml`, `.circleci/**`, `.buildkite/**`, `**/Jenkinsfile`, `.travis.yml`, `.drone.yml`, `appveyor.yml`, `azure-pipelines.yml`, `bitbucket-pipelines.yml`, `noxfile.py`, `**/justfile`, `**/Justfile`, `**/.justfile`, `**/JUSTFILE` |
| snapshot  | `**/__snapshots__/**`, `**/golden/**`, `**/*.golden`, `**/*.snap`, `**/expected/**`, `**/*.expected` |
| lockfile  | `poetry.lock`, `uv.lock`, `package-lock.json`, `pnpm-lock.yaml`, `requirements*.txt`, `requirements*.in` |
| docs      | `**/*.md`, `**/*.rst`, `**/README` |
| prod      | everything else |

Roles are resolved in the order guardrail → ci → snapshot → lockfile →
conftest → test → docs, so an earlier role wins: `.claude/settings.json` is
guardrail, not prod. A `.md` file that is also a guardrail path is guardrail.
This table is the whole default set, and `tests/test_spec_roles_pinned.py`
fails if it drifts from `config.DEFAULT_ROLES` — it had, silently, between
2026-08-02 and 2026-08-07: the pytest-configuration globs were added to the
code and never to this table.

**A JS/TS test path keeps its test obligations whatever role it holds.** A path
`frontends/javascript/paths.py` classifies as a JS/TS test (THREATMODEL row
107) takes the role `test` unless the order above resolves it to guardrail,
ci, snapshot, lockfile or conftest. It then keeps that role and that role's
rules, and every test rule still judges it (#197). The IR marks such a file
with the optional FileIR boolean `test_obligations`, default false; `role`
stays the published role, so no fingerprint identity moves. Bun's and Deno's
own names (`*_spec`, `*_test.tsx`) are JS/TS test paths only for a file whose
source names that runner, by a `bun:test` import or a `Deno.test` call (#196
186.4), and so are AVA's and tap's own layouts (`tests/**`; tap's
`__test__/**` and `*.tests` names) for a file whose source imports or requires
`ava` or `tap` (#233). A rename is an edit of the test, not its disappearance,
when the runner that ran it still collects the new path (§2b), whatever roles
the two paths hold. A Python file carries test obligations exactly when
pytest's default collection runs it (§2b), whatever role it resolves to
(#219): `tests/golden/test_x.py` keeps the `snapshot` role and its rules, and
every test rule judges it beside them, while `tests/golden/data.py` stays a
snapshot only. Moving `tests/test_x.py` there removes no test.

**A file beneath a test-support directory is a test whatever its extension.**
A path that would be `prod` and has a `__tests__`, `__mocks__` or `test`
directory segment (whole segments, any case) takes the role `test` unless it
is a Python file (#217). Fixture data, manual mocks and helpers there serve
the tests, as every file under `tests/**` already does. So editing one is not
production repair evidence and grants no opaque exemption (THREATMODEL
row 2), and neither does a rename out of such a directory. This is an engine
overlay on the table above, not a default glob: the IR's `role` reads `test`,
while E7 judges the file by its table role (§5). A path that the table or
runner promotion (below) resolves to any other role keeps it.

**One role is decided by content, not by path.** A `prod` file is
reclassified `ci` when it is *shaped* like a runner script — a `.sh`, `.bash`,
`.zsh`, `.ps1`, `.bat`, `.cmd` or `.mk` suffix, a `Makefile`/`makefile`/
`GNUmakefile` basename, or a shell shebang (`sh`, `bash`, `zsh`, `dash`,
`ksh`, `ash`, including via `env`) — **and** either side of the diff actually
invokes a test runner. Python files are never reclassified this way;
`noxfile.py` is covered by path instead. Nor are JS/TS test paths, the test
runners' zero-configuration layouts the engine treats as tests
(`frontends/javascript/paths.py`, THREATMODEL row 107): such a file names its
own runner, so the content gate would hold for every one of them as soon as a
shebang or a `Makefile` name prefix supplied the shape (#197).

The discriminator has to be content because the filename cannot separate the
two cases: a Makefile whose `test:` recipe runs pytest *is* the test command,
while a Makefile that compiles an extension is production code whose edit is
real repair evidence. Classifying by name in either direction is a measured
error — as `prod`, weakening the runner was invisible and touching it granted
the diff the §THREATMODEL-4 opaque exemption (rows 61–67); as `ci`, every
build Makefile would stop being repair evidence.

**A `package.json` or `Pipfile` is `ci` when its test command changes.**
`npm test`, `yarn test`, `pnpm test` and `bun run test` run `scripts.test`
whatever it says, and `pipenv run test` runs `[scripts] test`, so a
manifest's test command is decided by its keys first (#174): `test` and
`test:*`, then any script that invokes a recognised runner, then, one hop
further, the scripts that `test` or a `test:*` script names through a script
runner (`npm run`, `yarn`, `pnpm`, `bun run`, `run-s`, `run-p`,
`npm-run-all`, `pipenv run`). A diff that changes the test command makes the
manifest `ci` for that diff, with no opaque exemption. A manifest contributes
only its test command: dependency, version and metadata edits keep it
`prod`, and the weakening scan and its narrowing base (§4) read only the test
command (#196 185.1). A side Python cannot read is not a missing test
command: any edit to it counts as a change, and the scan then reads the
manifest whole.

## 2b. Collection semantics

A role says what a file is *for*; collection says whether its tests actually
execute. greenwash models pytest's default collection, because every gap
between the two is a laundering route (all confirmed by reproduction):

- file: `test_*.py` / `*_test.py`, **and** a directory pytest descends into —
  its default `norecursedirs` skips dot-directories, `build/`, `dist/`,
  virtualenvs and the like, so a move into one is a disappearance exactly as
  a rename out of the filename set is (both in range and worktree mode)
- class: `Test*` — **plus every `unittest.TestCase` subclass, whatever it is named**. pytest's `python_classes` setting does not gate unittest collection: `class BillingTests(unittest.TestCase)` runs. This line used to read "methods of a non-matching class are never collected", which is false about pytest and was the premise the implementation was built on — a `unittest.TestCase` subclass not named `Test*` produced zero units and every detector was inert on it (THREATMODEL 86, found 2026-08-09)
- function: `test*`, and only at module level or inside a collected class.
  pytest collects a module's or a class's tests from its `__dict__` once
  the scope has run, so a name's last binding is the one that runs (#424).
  Every syntactic binding of the name in that body counts: a def or class,
  an import, `=` (annotated or augmented, or one target of a tuple),
  `with … as`, a walrus, a `match` capture, `del`, `except … as` and a for
  target, and, for a class's names, a module-level `Cls.name = …` or
  `del Cls.name` after the class; so does a literal-name `setattr`,
  `delattr` or `globals()[…]`. An annotation without a value and a for over
  a constant-empty iterable bind nothing. A def or class that a later
  binding certainly replaces (on a straight-line path, or under branches
  that always hold) is no unit, and a rebound class takes its units with
  it, so a no-op def appended under a test's name is an in-place rewrite of
  that test. One that a later binding may replace stays a unit with a
  `collection.rebound` marker (§4 `TEST_DISABLED`): its guard is that
  binding's condition, or none D6 can hold when the binding is in a loop
  body, is an `except … as` or for target, is in a `match` case, or comes
  mid-way through a `try` body. Bindings on exclusive paths do not rebind
  each other: if/elif/else arms, `match` cases, separate except handlers, a
  handler and the try `else`, and a handler and the try body when nothing
  after the try-body binding can raise. `X = f(X)`, or a nested
  one-argument chain, is read as `@f` would be: a skip or xfail applied
  this way is that mark, and an unknown wrapper keeps the test live. A def
  or class that a collected name captured before the rebinding
  (`test_y = test_x`), and a rebound class's method that an earlier
  same-file subclass still runs, stay as they were, unless same-file C3
  resolution proves that no collected class runs them. The same-named
  units that remain are kept distinct as `name`, `name#2`, … in file
  order, so a comment-only edit cannot produce phantom pairings. Computed
  names, `exec`, star imports, metaclasses and class decorators are not
  read (THREATMODEL 135)
- statements after an unconditional `return`/`raise` never execute, and
  neither do bodies of nested `def`/`class`/`lambda`. Branch conditions are
  **constant-folded**, not pattern-matched: `if False:`, `if not True:`,
  `if 1 == 2:`, `if False and x:`, `for _ in []:` and a `match` on a literal
  that no case can meet are all dead. Assertions there are not collected
  (their loss reads as removal). A def or class at module or class level
  under a dead arm never runs either, so it binds nothing and is no unit, and
  a class takes its units with it: its loss reads as a disappearance, as a
  deleted test's does, and it earns no move, restructure or survivor credit
  (#499). The arms are the ones the reading of later bindings above decides
  dead: the arm of an `if` that a folded condition rules out, the body of a
  `while` whose condition folds to false and of a `for` over a
  constant-empty iterable, every case of a `match` that no case can meet,
  and the handlers of a `try` whose body cannot raise. A def under a
  condition the folder cannot decide, such as `if os.environ.get("X"):`,
  stays a live unit with no marker, a named residual
- `__test__ = False` at module or class scope removes it from collection —
  pytest checks it before anything else
- `@pytest.mark.parametrize` rows are test items: deleting rows deletes units,
  and so does marking them `pytest.param(..., marks=pytest.mark.skip)`, because
  a row is an item only if it runs
- pytest's own configuration decides collection, so `pytest.ini`,
  `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini`, `setup.cfg` and
  `pyproject.toml` are test-runner config: *introducing* a
  narrowed `python_files`/`testpaths`, or a filtering `addopts`, is a weakened
  test command. Moving one between files is not — see §5's two token families.
  A value written over several lines is read to its end: a TOML array to its
  closing bracket, and an INI value, quoted or not, over every indented line
  after it (#324, #327). In `[pytest]`, which pytest 9's `pytest.toml` uses
  too, a quoted value stops at a line that reads as a TOML setting
- `conftest.py` is analysed for suite-level collection controls
  (`pytest_collection_modifyitems`, `pytest_ignore_collect`,
  `collect_ignore`/`collect_ignore_glob`, `add_marker(...skip)`). A
  `pytestmark` in `conftest.py` is not one: pytest does not collect
  `conftest.py` as a test module, so it never reads the mark. It is reported
  at info, as a line that disables nothing (#209 Q3).
  For `collect_ignore` this means *every statement that puts a path into it* —
  assignment, `+=`, `extend`/`append`/`insert` — because only the assignment
  form used to count and the idiomatic spelling therefore dropped whole files
  in silence (row 70). An assignment of an **empty** list is an initialiser,
  not a control. Each control carries a guard, the condition it acts under, so
  `if not PY_3_14_PLUS: collect_ignore.extend([...])` is judged as the compat
  gate it is. A `collect_ignore` statement's guard is its enclosing `if`,
  `else` or `except`. A collection hook's is the path condition to each of its
  effects (#209 Q1): every enclosing `if` test, `not (...)` for an `else` and
  for the code after a branch that always ends (the `--runslow` recipe's early
  `return`), and an `except` block's condition, through loop bodies. A hook is
  a control only when it has an effect that can drop or disable an item
  (#209 Q2). A reorder of the items list (`items.sort(...)`,
  `items[:] = sorted(items, ...)`) and an `add_marker` of a mark that only
  labels an item are none, so a hook whose only effects are these reports
  nothing. A mark labels an item unless its name contains `skip` or `xfail`, or
  it is `usefixtures` or pytest-dependency's `dependency`, which act. Beyond
  these, an effect is anything in the hook that checkwash cannot show to be a
  read, so an effect it cannot read still counts, and a condition that names an
  item selects items and is no part of the guard. An `add_marker(...skip)` call
  takes the guard of the hook path it sits on, and has none outside a
  collection hook. The recorded guard is the **weakest** across every control
  of one name in the file, so one unguarded drop cannot hide behind an honest
  gate beside it, and a gate under another name lends it nothing (§5 D6, #208)
- an **unguarded** suite-level collection control is **not** de-escalated by
  repair evidence. Unguarded means it has no guard that can be false: none, or
  one that holds in every environment checkwash evaluates, and a guard edited
  to one that always holds leaves its control unguarded (#209 Q4). A production
  change explains a rewritten expectation; nothing about it makes
  it correct to stop *collecting* tests. A qualified compatibility gate (§D6)
  does explain it and still de-escalates. When an unguarded suite-level
  control in a `conftest.py` blocks (a collection control above, or a runtime
  one such as a fixture whose setup always skips), its escalator states a fact
  about the diff, not about evidence: `COLLECTION_CONTROL_UNEXPLAINED` if the
  diff changes any production-role file, `NO_PROD_CHANGE_IN_DIFF` if it changes
  none. This is a label, not evidence: severity is high either way (#205)
- `conftest.py` is also analysed for suite-level **runtime controls**: code
  that leaves a test collected and keeps its failure from failing the run.
  Beside the execution and report hooks of #84 (a `pytest_runtest_makereport`
  that rewrites the outcome to `passed`, for one) and a fixture whose setup
  always skips, two families are read, in the next two items: code that
  forces pytest's exit status (#422) and a no-op swapped in for what pytest
  runs (#432). A runtime control's marker carries no guard. Where an effect
  sits under a condition, in #84's hooks and in both families, the condition
  is hashed into the marker's name, so a changed condition is a new control;
  D6 `COMPAT_GATE` has no guard to judge, and the control is unguarded in the
  sense above, so repair evidence does not hold it. TEST_DISABLED reports a
  runtime control the diff adds on the conftest's `<suite>` unit, at high,
  labelled as above; one the base already had is not reported again
- code that forces pytest's **exit status** is a runtime control (#422).
  pytest exits with the status the session ends with unless the process ends
  first, so a conftest can turn a failing run green without touching a test.
  The marker is `conftest.runtime.exit.<place>.<effect>.<hash>`: `<place>` is
  the function the effect sits in (`module` at module scope), `<effect>` is
  `exitstatus`, `testsfailed`, `pytest-exit`, `os-exit` or `system-exit`,
  and `<hash>` is taken over the path condition. Read anywhere in the
  conftest: a write of `exitstatus` or `testsfailed` on any receiver (an
  assignment, augmented ones included, a `del`, `setattr`, `__setattr__` or
  `delattr` with a literal name, a literal key of `x.__dict__` or `vars(x)`,
  or a keyword or literal dict key of their `update()`), and
  `pytest.exit(..., returncode=v)` or a call of `pytest.exit.Exception`,
  `Exit` or a same-file subclass. Read in a place: `os._exit(v)` under any
  alias, called or passed as a callable (`atexit.register(os._exit, 0)`),
  and, outside `pytest_cmdline_main`, `sys.exit(v)`, `exit()`, `quit()` or
  a `SystemExit` or same-file subclass, called or raised, the three
  functions also when passed as a positional argument. A place is module
  scope; every function or method named `pytest_*`; every fixture; every
  callable passed to, or decorated by, `atexit.register` or an
  `addfinalizer`; the lambdas in a place; and every same-file function a
  place calls by name, transitively, with a same-file class's `__new__` and
  `__init__` when the class is called and its methods when called through
  the class name. A value is read as a POSIX exit status, modulo 256: 0
  (`False`, `ExitCode.OK`, and `0.0` for a write or a returncode) and 5
  (`ExitCode.NO_TESTS_COLLECTED`) count, and so does any value this reading
  cannot show to be neither, a named constant included. No value, or
  `None`, is 0 for a write and for `SystemExit`; `pytest.exit` with no
  returncode, or `None`, interrupts the run or keeps its status and counts
  for nothing; `SystemExit` with a string or a float prints it and exits 1.
  A `testsfailed` write counts unless it writes a truthy literal or adds a
  positive one (`+= 1`). The status the run already had is no effect: in a
  `pytest_*` function implementing `pytest_sessionfinish` or
  `pytest_terminal_summary` (by its name, or the hook its
  `hookimpl(specname=...)` names), its own unrebound `exitstatus` parameter,
  `session.exitstatus` on its own unrebound `session` parameter, `int()` or
  `ExitCode()` of either, and a zero under a positive conjunct
  `exitstatus == 0` (`== ExitCode.OK`, `not exitstatus`) over either. None
  of this holds when the conftest calls or names that function anywhere
  else, since it could pass a forged status. The recipe that turns "no tests
  collected" into success is no control either: a zero written to
  `session.exitstatus` in such a `pytest_sessionfinish`, under a positive
  conjunct, not negated and not in an `or`, that compares its status with 5
  by `==` or `is`, by `in` a literal tuple or set of 5 alone, as a `match`
  case, or in `0 if exitstatus == 5 else exitstatus`. pytest returns 5 only
  when nothing failed. Code that never runs is not read: an
  `if __name__ == "__main__":` block in a module that never binds
  `__name__`, a branch a literal test rules out, an undecorated nested
  function its enclosing function never names, and `os._exit` in a fork
  child (under a positive `pid == 0` or `not pid` over a name bound once, in
  the same function, to `os.fork()` or `os.forkpty()[0]`). A called `exit`
  or `quit` is not the builtin when only unconditional module-level imports
  that precede it bind the name (`from pytest import exit`); a passed one
  is not the builtin either when a parameter or another binding in its
  scope, an enclosing scope or module scope holds the name. Not read (#422
  Q4, Q5): `pytest_cmdline_main`, `pytest_runtestloop` and
  `pytest_collection` short-circuits; callbacks registered another way
  (`config.add_cleanup`, `signal.signal`, `threading.Timer`,
  `weakref.finalize`); other plugin modules; exits in test modules or
  production code; `os.exec*` into a no-op; computed names (`getattr`,
  `__import__`, a computed `update(**...)`); rebinding pytest's own
  functions beyond the next item; `ctypes`; interpreter start-up files; and
  the recipe together with a run that collects no test, which the resolved
  collection inventory (§4 `CI_WORKFLOW_TOUCHED`) still takes to fail
- a **no-op swapped in** for what pytest runs is a runtime control (#432).
  Three direct spellings are read, each under its own effect, so a later
  write to one never clears another: `item.runtest`, `item.obj` or
  `item._obj` written on the `item`, `pyfuncitem` or `nextitem` parameter of
  a top-level, non-async `pytest_runtest_protocol`, `pytest_runtest_setup`,
  `pytest_runtest_call`, `pytest_runtest_makereport`,
  `pytest_runtest_teardown`, `pytest_pyfunc_call` or `pytest_itemcollected`
  (`item-runtest-replaced`, `nextitem-obj-replaced`, ...; `pyfuncitem` reads
  as `item`); `runtest` written on `pytest.Function`, `pytest.Item`,
  `_pytest.python.Function` or `_pytest.unittest.TestCaseFunction`
  (`Function-runtest-replaced`, ...); and a native `unittest.TestCase`
  method written (`testcase-assertEqual-replaced`, ...): an assertion
  method of Python 3.11–3.13 or a deprecated alias of one, `fail`,
  `_baseAssertEqual`, or `_callTestMethod`, `run`, `__call__` or `debug`,
  which run a test (`TESTCASE_METHODS` in
  `frontends/python/runtime_controls.py`). A write is an assignment or a
  `setattr` with a literal name, on the object itself or through a simple
  alias (`node = item`, `Case = unittest.TestCase`,
  `from unittest import TestCase as Case`). The marker is
  `conftest.runtime.<hook>.<effect>.<hash>`. The class and TestCase writes
  are read at module scope, where `<hook>` is the `module` pseudo-hook and
  never a fixture, and in the body of any top-level, non-async `pytest_*`
  function. Only a lambda or an undecorated same-file function is read as
  the replacement. An item callback or item-class `runtest` replacement is
  a no-op when no call anywhere in it, nested scopes and defaults included,
  mentions a carrier of the original. Carriers are traced, not matched by
  spelling, and generously toward silence: the item and its aliases,
  pytest's item classes, a class-level replacement's first parameter, every
  name bound or written from an expression that mentions a carrier, and
  every name bound in a statement this reader does not enter. A TestCase
  replacement is a no-op, one that cannot fail, only with no call, `raise`
  or `assert` anywhere in it. A later write to the same attribute that is
  not a no-op, or its `del`, clears that attribute's effect only. Not read,
  each pinned silent by a named test in
  `tests/test_issue432_noop_replacement.py`: loops, `with` and `except`
  bodies, async hooks, hooks bound by assignment, class plugins, autouse
  fixtures, replacements built by a call or taken from another object's
  attribute, computed names, `__dict__` writes, subclasses, `sys.modules`
  lookups, `addTypeEqualityFunc`, a hook or module scope whose unknown
  conditions branch into more than 64 paths (then not read at all), and
  the others named there
- module-level `pytest.skip(..., allow_module_level=True)` and
  `importorskip` disable the whole file
- a skip marker's identity includes its **condition**, so
  `skipif(False)` → `skipif(True)` is a change; and the marker is matched on
  its trailing components, so `import pytest as p; @p.mark.skip` counts

For JS/TS, collection is the default discovery of the runner that runs the
file, matched case-sensitively, as the runners match it
(`frontends/javascript/runners.py`; #196 186.7, 186.3). The runner is the one
the file names by import or require (`vitest`, `@jest/globals`, `node:test`,
`bun:test`, `ava`, `tap`) or by a `Deno.test` call, else the one the base
side's root `package.json` names alone among `jest`, `vitest`, `mocha`,
`jasmine`, `ava` and `tap` (#233), else unknown. A rename reads the moved
file's base side. Unknown falls back to the union of the Jest and node:test
defaults. A move to a path that runner does not collect is a disappearance.
When the runner does not collect the old path by default either, the project
configures its own globs, which are not read, and the union decides.

A JS/TS test callback's assertions are those its statements reach (#429).
One bounded walk reads the statements of a callback's block body. The
statements after an unconditional `return` or `throw` never run, and
neither does a branch a literal-only folder decides: the body of an `if`, a
`while` or a three-part `for` whose condition folds false, and the `else`
of an `if` whose condition folds true. The folder reads literals, `!`,
parentheses, `&&` and `||` as the Python fold reads `and` and `or`, `===`
and `!==` between literals, the other comparisons between literals of one
primitive type, and `undefined` and `NaN` only where they name the
unshadowed global; anything else is unknown, a `const` binding included. A
block and the selected branch of a decided `if` pass their termination on.
Loop, `do`, `try`, `catch`, `finally` and labeled bodies are read inside,
but a `return` there ends nothing after them, and function, arrow and class
bodies are not read, iterator callbacks included. An expression statement
of `&&` or `||` whose literal operand decides it skips the assertion that
is its last operand and runs to its end, when the statement starts on a
boundary the walk proved. Where the walk cannot prove a statement's end,
it stops reading that statement list, and the assertions after keep their
reading. The catch evidence of `BROAD_EXCEPT_ADDED` (#363) still reads every
assertion a callback spells. `docs/js-reachability.md` names the residuals.

A JS/TS test or block registered where no run of the file reaches is no unit
(#484). The same walk reads the module's own statements, stepping over a
static `import` declaration whose end it proves (`export`, TypeScript's
`import x = require(...)` and an import with attributes stop it), the block
callback of every `describe`, `suite` and `context` declaration, their `x`
and `f` forms included, and the callback of a test that registers a named
test or a block of its own (node:test's and tap's `t.test`), even one with
no assertions. A declaration that starts where the walk proves no statement
runs is no unit, and neither is any declaration inside it. Its loss is a
disappearance, its skip, focus and options apply to nothing, and it earns no
D2, D5 or D10 credit. An expression statement of `&&` or `||` whose literal
operand decides it skips a declaration call that is its last operand, as it
skips an assertion. A dead region that holds a function declaration, which a
call before it may run, refuses the walk; a function expression there does
not, except a named one in a position the walk reads conservatively as a
declaration's, such as an object property's value after `:` (D-165 reading
6; THREATMODEL 159, residual 6), which refuses it too. A condition the
folder cannot decide (`if (process.env.CI)`) leaves the registration live.
Its assertions still reach the catch evidence, and a file whose only tests
are registered in dead code still declares tests.

A JS/TS table on `test` or `it` (`test.each`, `it.each`, `test.for`, with
chained modifiers such as `test.concurrent.each`, in the call and the
tagged-template form) is one unit, named by its title as written, whose
callback is read as a test's (#428). Its rows are its test items, as
`parametrize` rows are: deleting one deletes an item, and a plain test whose
pair is a table of no rows, or of rows that cannot be counted, is the one item
it was, lost. Rows are counted for an inline array literal with no spread or
hole, a tagged template whose cells divide by its headings, and a same-file
`const` bound once to such an array literal, not exported and read nowhere
but as a table argument. Any other table's rows are unknown, and between two
tables the count is not compared when either side's rows are unknown. A
column is identified by its row's position (`#0`, `#1`, ...), its object key
or its template heading (`#expected`), never by the callback's parameter
names: `.each` spreads an array row into the parameters and `.for` passes it
whole, and an object or template row goes to an object pattern by key. A cell
is canonical: a Number or a quoted string by its value, anything else by its
text without formatting. A table callback's first parameter is its row, not
its test context; `.for` passes the context second and `.each` none. The rows
of a `describe.each` table are not read, and the units inside it are read as
any others. A TypeScript type argument after `.each` or `.for`
(`test.each<Row>([...])`) ends the declaration, so such a table is no unit.

### Bounded Python carriers and table projection

A direct conditional failure, `if comparison: raise AssertionError`, can
carry an oracle when its single comparison and built-in exception binding
are known. It has no else/cause/side-effecting body or dynamic message.
The analysis AST retains source spans and supplies the same carrier to
reachability, inherited-oracle and exception-neutralization logic. General
control-flow programs and custom exception semantics are not inferred.

An inline transparent truthiness carrier can expose a scalar equality when
its top-level class has only a two-field constructor and a one-return
`__bool__` equality. Bases, decorators, metaclasses, special attribute fields,
other methods, dynamic class hooks and module/test rebinding are excluded.
The actual call and literal expectation must project to exact built-in
str/int/bool/None values using unchanged, strict, pure production source;
string projection is ASCII-only. Each source side is resolved independently,
and unsupported types or context leave its ordinary truthy representation.
The original native assert text/span is retained. This does not model general
custom equality or execute a repository class.

Literal parametrize, fixture(params=), and loop consolidation can project
concrete oracle cases when the complete before-side call/input sequence is
preserved as an ordered prefix; new cases may follow it. One baseline case
is sufficient. Plain zero-argument single-assert tests and supported table
carriers can occur on either side. Modules may also contain a docstring and
uniquely assigned literal constants or named literal tables. The diff may
include sidecars only when their inertness is proved independently: unrelated
documentation, literal-only modules, or AST-identical source. Imported
production, package startup and unproved configuration/data changes withhold
the projection. Repeated bound row references are rejected so
substitution cannot turn aliases into separate literal objects. The bounds
are 65,536 source bytes, 4,096 AST nodes and 64 concrete cases per side.
Expected expressions remain separate so expectation edits still
reach ordinary detectors. Generated `test_concrete_*` identities denote
concrete cases rather than source function names; evidence spans still refer
to the source. The bounded projection does not alter alignment thresholds,
strength values, severities or the existing fallback restructure policy.
Unsupported shapes retain their ordinary findings and do not gain this proof.

The unreleased T-326 candidate also handles bounded plain-class helpers,
matched wrappers and closed predicates. A string-helper block retains its
single subject-call assignment and all three auxiliary/result assertions;
each auxiliary oracle must match, with only closed literal specialization.
For a stateless `unittest.TestCase`, exact oracle multiplicity plus separately
proved pure production calls on literal inputs permits method sorting and
`setUp` checks. This proves the suite's pass/fail conditions, not identical
call order or execution after an earlier failure. Additional setup checks,
state, implicit module hooks and unproved source withhold that credit.

A table whose rows delegate is projected the same way (v0.3.0, #136) when the
delegate is a same-file helper that is one message-free `assert` with plain
named parameters, no decorator and a name pytest does not collect under the
default `python_functions`, and each row's call passes only row names or
literals: the helper's assertion is inlined per row with its parameters bound
to that row's literals, so the helper is the oracle. A zero-argument
`@pytest.fixture` returning a literal table is a table source under the same
bounds. A same-file helper taking the literal table itself may contain one
loop with one assertion; both the table actual and row unpacking must resolve
within these bounds. Comparisons between ordinary parametrized rows in the
same unit retain the row-keyed detector ownership below. Anything else falls
back to the general frontend. The name test is a
cross-file assumption — it holds only under the default `python_functions` —
so `snapshot_context._default_collection_options` withholds the projection's
inert-startup proof whenever any collection option other than `testpaths` is
configured.

A bounded source carrier expansion also supports stateless same-file classes
and helper-only single inheritance, fully matched contextmanager/decorator
templates, and closed operator/literal-lambda equality helpers. Collection,
definition-time authority, method dispatch, object ownership and effectful
call consumption must be preserved before the same concrete-input proof can
apply. Arbitrary inheritance, decorators, fixture lifecycle and reordered
effectful calls receive no general refactor credit.

A separate additive pass can compare concrete old native assertions or
single-assert same-file helper calls with literal parametrize rows that add
`abs(result)` or the fixed alphanumeric-filter/join/lower input wrapper.
Callee imports, raw input, equality/identity operator and concrete expectation
must match; unchanged raw comparisons are reserved first as a multiset.
These events retain the original units and findings and give no equivalence
credit. General helper programs and arbitrary table transformations are not
inferred.

Redundant input normalization can withhold an ordinary wrapper finding only
for a closed ASCII-string literal call through fixed str methods or a
transparent same-file helper into a pure single-return production function.
Both concrete production expressions must project identically. The proof
bounds include 64 reads, 100,000 source bytes, 4,096 AST nodes, 16 expression
levels and 4,096-character ASCII strings. It proves the current concrete
expression, not every possible future production mutant.

Optional precision requires strict source context. Missing, failed,
incomplete or over-budget discovery withholds credit; selected-source read
failures retain their engine-error behavior. Inert repository test startup
and a complete bounded inventory (fewer than 64 nonempty Python sources)
reject conftest/package effects and unproved sibling test modules. Worktree
inventory includes untracked/hidden source trees, so it can withhold precision
when the committed range has a smaller complete snapshot. A directory symlink
in it is an opaque directory, as a submodule is (#414). This is not a
guarantee about arbitrary installed plugins or dynamic import hooks.

The context also probes pytest.ini, .pytest.ini, pyproject.toml, tox.ini,
setup.cfg, pytest.toml and .pytest.toml at source ancestors. Empty pytest
options and unrelated packaging metadata are allowed. `[pytest]`/`[tool:pytest]`
INI sections and pyproject `[tool.pytest.ini_options]` may also contain only
`testpaths` naming literal relative descendant directories that remain within
the ordinary collectability rules. Explicit files, globs, parent/absolute
paths, collection naming overrides, addopts, other options and nonempty native
pytest TOML files withhold the context-dependent proof rather than assuming
default collection. Invalid encoding/config syntax or an over-limit config
also withholds proof. Strict selected-source reader failures remain errors.

### Paired live pytest configuration evidence (D-183)

From 0.10.0, worktree checks and the managed Stop's analyses supply paired
pytest config evidence too. The primary worktree verdict pairs the diff's HEAD
with working-tree sources. A session-commits note pairs the recorded session
base with working-tree sources using a new context; it does not reuse the
primary context or substitute the session's policy-loading base for the
primary diff's HEAD. Each context is prepared once per analysis.

Working-tree config evidence is a bounded read-once cache of regular sources,
not an atomic filesystem snapshot. Inventory/mode facts are retained for the
analysis; selected source presence/modes must remain consistent with that
inventory and bytes of changed controls must match the captured diff, using
the engine's same lexical slash spelling for changed-path matching. Rename
old paths are bound to captured absence unless another explicit change
in the complete captured change set supplies that old path's after bytes;
iterable changes are retained before the two passes so generators obey the
same rule. Explicit old-path changes take priority regardless of ordering. Config
records retain exact bytes and compute content OIDs in the repository's object
format, with revision `worktree`; that label makes no committed/stored-object
claim. Existing per-source, batch and paired evidence limits apply. Config
records/deltas remain internal to the two pytest-control consumers and do not
become general Python/provider source or new physical diff entries.

Git BASE/head config evidence retains its existing one-hop same-tree regular
target capability. Working-tree evidence preserves ordinary source admission:
it reads regular files only, never follows worktree file/directory symlink data,
and refuses outside-repository, nonregular, inconsistent or over-limit sources.
Metadata resolves only the parent for the repository-boundary check and uses
lstat on the final component, without resolving a final file-link target.
Recognized logical aliases are considered before relevance gates, so an
unavailable worktree alias is NOT_ANALYSED rather than silently ignored. The
regular-only worktree limit is deliberate; it does not claim the frozen Git
link capability also exists on the live filesystem. Engine errors remain exit2
in normal formats and the existing Stop systemMessage/no-decision behavior;
session-note failure preserves the primary verdict and reports unanalysed
session commits.

## 3. Assertion strength lattice

**What counts as a unit's assertions (v0.1.26).** The IR records the
assertions a collected test *executes*, not the `assert` statements written
inside it: its own direct asserts, excluding those in nested scopes nothing
invokes, plus the direct asserts of same-file functions, lambdas, classes and
`@contextmanager`s the unit invokes, followed through the file's own call
graph to a depth of four. *Invokes* means invocation, not mention —
`callable(f)`, `hasattr`, `getsource(f)` and `f.__name__` name an oracle
without running it — and construction is not invocation: `partial(...)` binds,
and a `@contextmanager`'s body runs only under `with`. Helper-borne assertions
carry `inherited: true` in the IR, and a pair that crosses the unit-body
boundary in either direction is an extraction or an inlining — the slot moved,
not the assertion — so it is never reported as a substitution (THREATMODEL 91,
D-044). Cross-file helpers are out of scope and stated as such (91a).

Since #306, a method unit's call through its instance,
`<receiver>.<name>(...)` with the receiver its first positional parameter,
also runs a helper method: the one the class running the test resolves (the
method's own class, or the collecting subclass of an inherited test) in a
local C3 order over the file's top-level classes, where a base the file does
not define is an opaque entry and the name resolves only before the first
one. It is followed as a module helper is, once per entry site and at most
four calls deep, and its assertions carry `via`, the method's
class-qualified name. A call stays unresolved when the name is one
`unittest.TestCase` defines, when the binding is not exactly one
undecorated plain def in its class body, when a class of the order up to
the binder carries a decorator that is not transparent (below), when a
class of the order has a keyword or defines `__init_subclass__`,
`__getattribute__` or `__setattr__`, when the order is not a C3 order or
the module binds the name of a class in it again, and when the module
stores or deletes `.<name>`, names it in
`setattr`/`delattr`/`object.__setattr__`, `patch.object` or
`monkeypatch.setattr`, or calls `setattr` with a computed name on the
receiver or a class of the order (D-145, D-149). Since #502 (D-159) the
module also names it in a call whose last name is `__setattr__` or
`__delattr__`, by its name argument: the first of a bound call
(`self.__setattr__("_check", f)`) and the second of an unbound one
(`type.__setattr__(C, "_check", f)`), told apart by how many positional
arguments the call has; as a keyword or a literal dict key of
`update()`, or the literal key of `setdefault()`, on `x.__dict__` or
`vars(x)`; and, in a class body, as a literal key of `vars()` or
`locals()` that is stored or deleted, or that those calls, `__setitem__`
or `__delitem__` write. No name in the module resolves after a store into
or a deletion from `x.__dict__[...]` or `vars(x)[...]` with any key
(`vars(C)[...]` on a class raises at run time, as `C.__dict__[...]` does,
and is read the same way), a `__setitem__` or `__delitem__` call on
either, a store or deletion of `x.__dict__` itself (`=`, `|=`, `del`, or a
literal-name setattr of `__dict__`), or one of these writes whose name is
not a literal: a `**` argument or another mapping in `update()`, a
computed key, a `__setattr__` or `__delattr__` with no literal name, with
a starred argument or with an argument count neither form takes, or a
`setattr` or `delattr` whose target or name is a starred argument. A
computed-name `setattr` or `delattr` through a plain alias of the receiver
or of a class of the order counts as one on it, one hop, and only from
`x = C`, `x = type(self)` or `x = self.__class__` bound in the call's own
scope, a def or lambda around it, or the module; another value, such as
`cfg = self.settings`, is not followed. One whose target is reached
through a subscript or another call, such as `globals()["C"]`, counts as
one on every class. `vars()` and `locals()` outside a class body rebind no
method. An unresolved call adds
no assertion to the unit, as before #306, but across a diff it does not
keep the reading it had before #306: a call resolved at the parent and not
at the commit reads as the helper's assertions removed, and one resolved
at the commit only reads nothing as removed. A class decorator is
transparent only in a fixed list of forms, read through the module's
imports (`import pytest as pt`, `from pytest import mark` and `from
unittest import skipIf` included) and called with no `*` or `**` argument
(D-149): `pytest.mark.<name>`, bare or called, but not called with one
positional argument, and no keyword, that is not a constant, which pytest
returns to decorate the class itself; and, from `unittest` or
`unittest.case`, `skip(<str>)`, `skipIf(<condition>, <str>)` and
`skipUnless(<condition>, <str>)`, with the reason a string literal given
by position or as `reason=`, and bare `expectedFailure`. A form that can
disable a test (the unittest ones, the marks `skip`, `skipif`, `xfail`,
`usefixtures`, `dependency` and `parametrize`, and any mark whose name
contains `skip` or `xfail`) is transparent only on the class running the
test, since the tests that class defines do not carry a base's decorators
(THREATMODEL 117), and only where that class's units carry it. A skip
form, unittest's or a mark `skip`, `skipif` or `xfail`, must be spelled as
the frontend reads a skip, by the trailing parts of the name as written: a
last part `skip`, `skipIf`, `skipUnless` or `expectedFailure`, or last two
parts `mark.skip`, `mark.skipif` or `mark.xfail`; so `@when(...)` under
`from unittest import skipIf as when` and `@m.xfail` under
`from pytest import mark as m` are not transparent. A `usefixtures` mark
must be bare or take only string-literal positional arguments and no
keyword, as the frontend reads it. A `dependency` mark, any other mark
whose name contains `skip` or `xfail`, and `parametrize`, whose
class-level rows the frontend does not read, are never transparent. No
form is transparent under a root the module binds more than once,
declares `global`, stores or deletes an attribute or item under, or that a
star import may bind; nor through a same-file value such as
`slow = pytest.mark.slow`; nor when a write anywhere in the module reaches
its package through the write's target, by any name an import binds into
the package or by a dotted string. A write is a store or `del` of an
attribute or item, a call whose last name is `setattr`, `delattr`,
`setitem`, `delitem` or one of their dunders, any call with a `patch`
component, or a dict method on, or with a first argument of, `x.__dict__`
or `vars(x)`, and only its target is read, never its value
(`setattr(pytest.mark, "slow", wrap)`,
`mock.patch("pytest.mark.slow", wrap)`, or `MarkDecorator.__call__ = wrap`
under `from _pytest.mark.structures import MarkDecorator`). So a write
whose target names anything imported from `unittest` takes every unittest
form in the file. Only the module's own name is bound again: by a
statement at module scope, under a module-level compound statement too,
by the header of a def, class or lambda there (decorators, bases, class
keywords, defaults and annotations), by an assignment expression there,
in a comprehension too, or by a body that declares the name `global`. A
class, def, assignment, `del` or import of the name inside any other
function, lambda or class body is read as binding a local name. These are
not read, a residual (D-149): a write the reading does not name (a setter
or patcher under a name it does not list, a write through a value the
file computes such as a same-file alias, a function parameter or a call's
return value, or into a module named by a string key such as
`globals()["pytest"]`, `sys.modules`, `__import__` or `importlib`); a
store in a conftest or plugin; a star import that binds a class's name;
and a class body whose metaclass's `__prepare__` returns the module's
namespace. Nor are these, a residual (D-159): an aliased `setattr`
(`s = setattr`); an alias more than one hop away, bound other than by a
plain assignment, or to another value (`x = globals()["C"]`); a
computed-name `setattr` whose target is a parameter that holds the class,
such as a `setUpClass`'s `cls`; `pop()`, `popitem()` or `clear()` on a
class body's namespace; and a namespace written through `monkeypatch.setitem`,
`operator.setitem`, `patch.dict`, an unbound dict method
(`dict.update(self.__dict__, ...)`), or `vars` or `locals` under another
name. A `via` assertion is a
detection-only overlay: the unit's own assertions pair as before, and the
`via` ones then pair among themselves and with the after side's own
assertions left unpaired; they earn no credit and add no requirement for
another finding (§5).

Strength is a totally ordered integer. Weakening = the aligned assertion's
strength decreases. Defined once, in `src/greenwash/ir/strength.py`.

| level | name         | Python examples (pytest / unittest) |
|-------|--------------|--------------------------------------|
| 100   | EXACT_STRUCT | `assertEqual` on container literal, exact snapshot compare |
| 90    | EXACT_VALUE  | `==` / `!=`, `assertEqual` (scalar) |
| 70    | APPROX       | `pytest.approx`, `assertAlmostEqual`, and the tolerance calls `math.isclose`, numpy's `isclose`, `allclose`, `testing.assert_allclose`, `testing.assert_array_almost_equal` and `testing.assert_almost_equal`, and `torch.testing.assert_close` (#222) |
| 60    | PATTERN      | `assertRegex`, `in` membership, `assertIn`, `pytest.raises(..., match=...)` |
| 50    | TYPE_SHAPE   | `isinstance`, `len(x) == n`, `assertIsInstance` |
| 40    | BOUND        | `>` `>=` `<` `<=`, `assertGreater` family |
| 30    | NON_NULL     | `is not None`, `assertIsNotNone`, `assertIsNone` |
| 20    | TRUTHY       | `assert x`, `assertTrue(x)`, any non-comparison expression |
| 10    | TAUTOLOGY    | both operands literal (`assert True`, `assert 1 == 1`), or the two sides of an equality are the same expression (`assert f(x) == f(x)` — it can never fail) |
| 0     | REMOVED      | assertion disappeared |

Assertion forms that cannot be classified (e.g. `assertRaises`, custom
helpers) get strength `null` and are **excluded** from weakening comparisons
(fail-safe: no guess, no noise). Their removal still counts for
`ASSERT_REMOVED`, with one exception (#434): a bare Python `pytest.raises(E)`,
`pytest.warns(W)` or `raises(E)` that the order fallback (§4) leaves
unpaired is paired, after the fallback, with an unused newly written call
that only adds `match=` (PATTERN): the same callee, the same expected types
(a name chain or a tuple of them, as a set) and the same other keywords. That
pair records no strength change. Where an excinfo assert folded into
`match=` takes that call in the fallback, the bare call still counts as
removed, and the finding says the raise is still checked by the new call. A
dropped `match=`, another expected type or another callee is no pair. The
JavaScript frontend records a call to a resolved
assertion API whose predicate it does not read the same way: `raises` for a
throw check, `unknown` otherwise (#196 190.5).

**JS/TS tautologies (#429).** The JavaScript frontend reads the TAUTOLOGY
rung in every assertion library it reads, unary matchers and `assert.ok(true)`
included. An assertion is TAUTOLOGY, whatever it evaluates to, when its
subject as written and every operand its predicate reads (an expected value,
a bound, a tolerance, a property name; never a message) are exact literals: a
number, BigInt, string, template without a substitution, regular expression,
`true`, `false` or `null`, or an array or plain object of them, read as
JavaScript tokenizes them (a `//` inside a template is no comment), through
comments, parentheses, `x!` and a cast to one named type. A name is never a
literal, `undefined`, `NaN` and `Infinity` included. An equality or an
inclusive bound is TAUTOLOGY, negated or not, when its two sides are one
operand: the same tokens once comments, parentheses, `x!`, a cast to one
named type, formatting and the outer no-op arithmetic Python strips (`+ 0`,
`0 +`, `- 0`, `* 1`, `1 *`, `/ 1`) are taken out of each; a spread and a
property value compared with its property are none. Such an assertion keeps
its subject, text, span and operand evidence, so a finding on its own
evidence keeps its identity, and records form `tautology` with no predicate
key and `positive=True`, so the predicate relation below never reads it as
the predicate it replaced. A pair whose new side is a tautology is a strength
drop, so where the relation had read it (`toBe(27)` -> `.not.toBe(total)`,
polarity inverted), the finding now reports the drop, under another key. A truthy spelling
(`assert.ok(x === x)`), the `trivial` reading of §5 and the other residuals
`docs/js-reachability.md` names are not read.

**Operands bound by name (#462).** The Python frontend reads each operand
of a unittest assertion method by position or, failing that, by the
method's own parameter name: `first`/`second`, `list1`/`list2`,
`tuple1`/`tuple2`, `set1`/`set2`, `d1`/`d2`, `seq1`/`seq2`, `expr1`/`expr2`,
`member`/`container`, `obj`/`cls`, `a`/`b`, `text` with `expected_regex` or
`unexpected_regex`, `expr`, and `obj`. It reads `pytest.approx`'s expected
value by position or as `expected=`. A keyword or mixed spelling is rated as
its positional twin is, so `assertEqual` on a container literal is
EXACT_STRUCT however its operands are passed. No operand is read from a
position at or after a starred argument. Some calls pass an operand
through `*` or `**` and have no keyword for it, so the operand cannot be
bound (`self.assertEqual(**case)`, `self.assertEqual(*pair)`). Such a call
records the method's form and strength and no subject, expected value or
names, and it is not trivial. A known oracle replaced by one is an
unverifiable replacement (ASSERT_WEAKENED, never mild). One such call
replaced by another is not compared (462.Q2). The raises family keeps its
positional reading.

A frontend may also record the predicate an assertion states, as one key of
`ir/predicate.py` (the JavaScript frontend does, since #198, and the Python
frontend records the bound keys, since #224): presence
(`=== null`, `=== undefined`, `== null`, truthiness, `=== true`,
`=== false`), equality (`===`, `==`) and bounds (`<`, `<=`, `>`, `>=`). Two
keyed assertions on the same subject are compared by predicate before the
lattice, so a strength drop between two keyed spellings proven to be the same
predicate, or a stronger one, is not weakening (`.to.be.null` ->
`toBeNull()`, `.to.exist` -> `.to.be.ok`). A hand-rolled tolerance,
`abs(x - centre) < bound` in Python or `Math.abs(x - centre) < bound` in
JavaScript, records what the magnitude measures as its subject, a numeric
literal centre as its expected value and the bound as an `abs=` tolerance
(#196 189.2), so its truthy and matcher spellings share a subject and a bound
key, and a rewritten centre is an expected value rewritten. A frontend may also record an
operand's source (`operand_source`): it decides only whether two spellings
state the same operand, and two bounds that name one bound are compared over
the values below, at and above it, so `< 80` -> `<= 80` is a widening.

APPROX epsilons are never compared as floats. The literal source text is
compared via `decimal.Decimal`. No floating-point arithmetic participates in
any verdict.

## 4. Rule IDs (frozen)

Base severity of every finding is `warn`; deterministic escalators and
de-escalators adjust it (§5). Detector internals are not configurable;
detectors can only be disabled whole.

| Rule ID | Trigger |
|---|---|
| `ASSERT_REMOVED` | an assertion disappeared from a surviving test unit |
| `ASSERT_WEAKENED` | aligned assertion strength decreased, **or** its polarity flipped with the subject unchanged (`==`→`!=`, `is`→`is not`, `assertTrue`→`assertFalse`, `assertIs`→`assertIsNot`) — same form and strength, opposite meaning. Polarity is whether the assertion asserts its predicate or that predicate's negation, not whether it is spelled negated: `toBeDefined()` asserts `!== undefined`, the negation of `toBeUndefined()`. When the subject changed too it is reported as a rewrite, not as an inversion: greenwash cannot verify the replacement is equivalent, and saying "proves the opposite" would be a claim it has not established. When both assertions carry a predicate key (§3), the predicates decide instead of the lattice: a same or stronger predicate is not reported; the same key with its polarity flipped is the inversion above; a predicate change that no old value survives **contradicts** the old assertion, and a bound whose direction reversed (`<`→`>`) is reported as **bound direction reversed**; an old predicate that implies the new one is a **predicate widened**, graded by its lattice drop; any other predicate change is an **unverifiable replacement** (greenwash cannot verify the replacement is equivalent), and so is a known tolerance replaced, on the same subject, by one the frontend cannot read (a JS `closeTo` delta, `toBeCloseTo` precision or hand-rolled bound that the frontend cannot read, or that a write may have changed, is unknown, not unchanged; so is a Python tolerance call's pair that is torch's dtype default or comes through `*args` or `**kwargs`, #222). Only the inversion says the test proves the opposite. An operand change within one key belongs to `EXPECTED_VALUE_CHANGED` or `TOLERANCE_LOOSENED` |
| `TEST_DISABLED` | skip/xfail marker added (on the function, its class, a `pytestmark` its class or module binds in any spelling, under the name a decorator would mint (#260), a native skip or xfail the test body calls or raises (`pytest.skip`, `pytest.xfail`, `pytest.importorskip`, `self.skipTest`, `raise unittest.SkipTest`, `raise pytest.skip.Exception`), read through the module's imports, each object under one name (trial's `SkipTest` is unittest's, and the py library's `py.test` is pytest, #310), so `pt.skip()` and a bare `skip()` imported from pytest count, a raised one is a skip rather than removed assertions, and a skip respelled through another name of its object is not a new one (#220), or a conftest suite control, or a skip/xfail in the setup a unit runs (a requested or autouse fixture, in the test module or in a `conftest.py` above it, resolved as pytest resolves it for the test (#223); xunit setup): unconditional, or under the guard that setup reaches it under, judged as a body skip's guard is (#196 183.2); a conftest fixture's value names are closed over that conftest first, with the namespace and closure limits in D-127), or a skip/xfail that a helper the test or its setup calls ends in, either a same-file one (a function the module defines, one nested in the caller, or a name bound to a lambda or to `partial` of one, called by its plain name, at most four calls deep, as assertions are followed) or, since #272's second stage, one a top-level `from M import f` binds, followed into M when M is the test or conftest module an imported assertion helper resolves to, where only an outcome every call of it reaches is kept: read as a setup callback is, under the conditions its call and every call on the way run under, judged as a body skip's guard is, and reported as added to a helper this test calls (`helper.<function>.<effect>`, #272), or that a helper method the test or its setup calls through its instance ends in, resolved as §3 resolves it and read under the running class's attributes, reported the same way (`helper.<method>.<effect>`, #306), a later binding of the test's name that may replace it, under the condition that binding runs under and judged as a body skip's guard is (`collection.rebound`, §2b, #424), a whole test unit disappeared (including out of collection, per §2b; a later binding of its name that certainly replaces it is one, #424, and so is a JS/TS test registered where §2b's walk proves no statement runs, #484, and so is a def or class moved under a branch that never runs, #499), or parametrized cases deleted or disabled — since v0.3.0 counted by row identity (cell texts read through `pytest.param(...)`, one table per decorator, stacked decorators a cross product of items), so a marked-off row is reported however many rows are appended beside it, and the finding says how many items are marks rather than deletions; a vanished unmarked row is left to the count (`vanished − arrived`), which is why an edited input stays silent and a deletion beside an appended row does too when its expected value survives. Replacing disappeared live rows with new input/answer pairs has a separate EXPECTATION_DEFINITION_CHANGED owner below (THREATMODEL 102, 102a). Row marks include statically true skipif conditions; false and unknown conditions do not disable a row. In a JS/TS test file, a unit that focus (`.only`, `fit`, `fdescribe`, `{ only: true }`) stops is reported as no longer running, with the runner condition stated (node:test honours focus only under `--test-only` or `--test-isolation=none`; #196 187.1). Which units a focus stops follows the runner (187.2): Jest's rule, under which a focused block keeps the units inside it unless a unit placed directly beside them is focused, unless the file's imports or the base root `package.json` name only Vitest, Mocha, Jasmine or node:test, whose innermost rule applies: a focused block that holds a focused declaration keeps only that declaration. Focus that the diff adds to a file that had none, while no unit of the file is reported as no longer running, is reported once for the file: Mocha and Jasmine apply focus to the whole suite, so every test outside the file stops. It is not reported when the runner is proven to keep focus in the file, by a `vitest`, `@jest/globals` or `ava` import or a base-side root `package.json` naming Jest, Vitest or AVA and no other runner (AVA runs each file in a worker of its own, #233); a node:test import is no such proof (#196 187.4) |
| `TOLERANCE_LOOSENED` | any individual tolerance on the call got wider. Tolerances are compared as absolute bounds where a conversion is defined (places p -> 10^-p/2; numpy's decimal d -> 1.5x10^-d, #222), otherwise per kind, via Decimal: `abs`, unittest's `delta`, decimal places (`assertAlmostEqual`'s `places`, `toBeCloseTo`'s precision) and numpy's `decimal` each state an absolute bound, and `rel` or several tolerances at once are compared kind by kind (#196 190.3); two assertions aligned by span order alone are not compared when both halves moved, the subject and the expected literal alike, a substitution that `EXPECTED_VALUE_CHANGED` reports (#196 189.2). A negated approximate comparison (`assertNotAlmostEqual`, `!=` or `not` around `pytest.approx`, a negated tolerance call or JavaScript matcher) passes when the values are far apart, so its tolerance orders the other way: it records no tolerance and is not compared (#284) |
| `SNAPSHOT_CODE_COCHANGE` | snapshot files and prod files changed in the same diff without test-logic change |
| `ASSERT_SUBSTITUTED` | an aligned pair produced by the **order fallback** — position, not text or subject — where both halves moved: the subject differs structurally and so does the expectation. The old assertion is gone and a different one holds its slot, while `strength_change` reads 0 and `assertions_removed` is empty. Requires a subject on both sides, so folding an excinfo assert into `pytest.raises(match=)` is untouched; a *wrapped* subject is `SUBJECT_NORMALIZED`'s, and a rename that keeps the expectation is neither |
| `EXPECTED_VALUE_HARDCODED` | new assertion literal equals a constant newly introduced in prod in the same diff |
| `EXPECTED_VALUE_CHANGED` | an aligned assertion keeps its form, strength **and subject**, but its expected side was rewritten: a literal value (the centre of a hand-rolled tolerance included, #196 189.2), a call-expression replaced by a literal (issue #60), a call rewritten to a different call (issue #61), or a literal replaced by a call checkwash neither folds nor resolves, or one such call rewritten into another (#226). Such a call's callee is rooted in a name the file never binds, a builtin or global outside the fold set (`int('75')`, `parseFloat('75')`) or a name bound nowhere; a literal replaced by what an import, a declaration or a same-file function gives is EXPECTATION_DEFINITION_CHANGED's, through the provenance channel, in both frontends. A conversion of one literal from a fixed set folds to its value and is a literal: Python's `float` and `Decimal` (`decimal.Decimal`) and JavaScript's `Number`, each only where its name can be nothing else. Python literals compare as Python's `==` compares them, so `78.75` -> `Decimal('78.75')` and `1` -> `1.0` are no change and `0.1` -> `Decimal('0.1')` is one; JavaScript compares one canonical Number. A name or call replaced by a literal is read in Python only (#292). Both sides used to have to be literals; that left independent-oracle calls invisible. The file-scoped form also reports a modified stored snapshot/golden/expected file when no parsed production symbol changed in a production file the diff did not add and no opaque production change exists. A Python production file the diff adds is not such a change, whatever it defines: nothing in a brand-new file explains rewriting an existing stored expectation, which is also why clause 3 of repair evidence (§5) ignores an added file (#463 Q1 (a)). A deleted one still counts. A pytest file kept under a snapshot directory is a stored expectation too (#219), so a test added there beside a new module reports this form as well (D-157). It uses content-bound identity. New/deleted expectations and real or unrelated co-changes to existing production code retain the existing snapshot policy: a changed symbol in any existing or deleted Python production file, whether or not a test reaches it, and any opaque production change (#463 Q2 (a), Q3 (a); THREATMODEL row 132). This is a path-role heuristic, not proof of which test reads a file. |
| `EXPECTED_VALUE_DERIVED` | an aligned assertion keeps its subject and its strength, but its expected side stopped being a literal and now resolves — through the unit's own assignments — to a name the subject also uses. `== 105.0` became `expected = sum(items)` / `== expected`. The transition is the signal: an expectation that was already computed before the diff is how the test was written. A literal replaced by a *named constant* or a parametrize argument shares no name with the subject and does not fire under this rule; bounded concrete expectation changes can still belong to EXPECTATION_DEFINITION_CHANGED; a literal replaced by an expression over the subject's own inputs is the test computing the answer from the data it feeds the code. Escalates through repair evidence like every oracle rule |
| `EXPECTATION_DEFINITION_CHANGED` | an aligned assertion whose **text is unchanged** and whose expectation resolves to something outside the assertion whose definition changed: a unit-local binding, a `parametrize` **column the expectation actually consumes**, a same-file `@pytest.fixture`'s return/yield, or a **same-file top-level constant** (canonical on both sides so reformatting is not a change; last-wins on both sides, which is module execution order, so an appended rebind is caught; a constant the subject also consumes is a shared producer and excluded — D-051, the 2026-08-25 census's largest blind bucket). Which column is the expectation is decided by consumption, not by position or by the name `expected`. Pure row additions and net deletions are excluded — those are `TEST_DISABLED`'s event. When live count does not fall, disappeared input rows whose consumed answers are replaced by different new answers also belong to this rule: input-only renames retaining the old answers have their own bounded owner in `SUBJECT_INPUT_CHANGED` since the issue #93 contract decision (D-060); pure append, disabled rows and skip-plus-append retain their prior behavior. A cell is read through `pytest.param(...)`, so marking rows skipped is not an expectation edit. Since v0.3.0 (#135) the parametrize comparison is row-keyed: rows are identified by their input cells and the consumed column is compared per key as a multiset — a key that disappeared is a deletion or the replacement event just described, a key whose answers still contain everything they had is an addition or a reorder, a key that lost an answer it had and gained one it did not is this rule's event — and every positional cell of a `pytest.param(...)` row is read, so a fully wrapped table is compared like a bare one; a single-column table has no inputs to key on, so its identity is position and the before cells must survive as a subsequence (insertion anywhere, edit or reshuffle reported). A binding that gains a **branch-exclusive alternative** is excluded the same way, and only then: the after side must have more definitions, every before-side definition must survive verbatim (multiset containment), and the name's bindings must sit in pairwise-exclusive `if`/`match` arms — a sequential rebind fails the third clause because the last unconditional binding is the one the assertion reads (THREATMODEL 95 records the tautological-gate residual). Compared structurally, so reformatting is not a change. Escalates through repair evidence like every oracle rule — and D9 `DEPENDENCY_DRIFT` and `PACKAGE_REPAIR` de-escalate it the same way. Blocking status is a measured decision taken twice, not a hedge: as a blocking rule in v0.1.19 it cost 12 extra blocks on 1800 human commits and shipped at `info`; after the T1.9/T1.10/T1.11 credit rounds the 2026-08-25 promotion sweep cost 5, each adjudicated false and named (`benchmarks/adjudication-2026-08-25.json`), inside the pre-registered line of five. A JS/TS `.each`/`.for` table's rows are read the same way (§2b, #428): the consumed column is one the expected operand names directly through the callback's own parameter (`toBe(sum)`, with `sum` an array row's third cell, consumes `#2`), a column the subject names is a shared producer, and a local computed from a cell, a member (`row.expected`) and an index are not followed |
| `SUBJECT_NORMALIZED` | an aligned assertion keeps its form, strength **and** expected literal, and the asserted subject now wraps its old self — `f(x)` became `f(x).replace(...)`, `sorted(f(x))`, `f(x)[0]`. Structural containment, so spelling does not matter. Resolved through **one hop** of the unit's own bindings, so hoisting the wrapper to the previous line is the same event; and applied to **argument positions** too, so `f(x)` becoming `f(normalise(x))` counts — same callee, same arity, every argument unchanged or containing its counterpart, at least one actually wrapped. Two hops are a stated residual; a subject replaced outright is a different test, not a laundered one. Escalates through repair evidence like every oracle rule, because wrapping is routine when production changed under it. Direct containment is retained alongside one-hop resolved containment. The bounded concrete ASCII-string proof below can establish that an added normalization is redundant for the unchanged production expression. Separate literal-table events can expose the same wrapper when ordinary assertion alignment does not; exact raw oracles that remain present are consumed first, so merely adding wrapped cases does not replace them. Neither extension changes severity or the ordinary restructure policy. |
| `SUBJECT_INPUT_CHANGED` | an aligned assertion keeps its form, strength, polarity and expected answer, and the subject's **input data** changed — `f("Hello")` became `f("hello")` while `== "hello"` stayed (issue #93). Bounded: the subject must be a plain call with the structurally same callee on both sides (a provider bound in the unit, as a same-file fixture or as a module constant must be defined identically, so a changed provider invents no evidence), and every changed argument must resolve to a concrete literal on **both** sides — directly, or through the straight-line local binding / module constant the assertion reads. A changed argument that resolves to the *same* value is a rename and stays silent, as do a computed argument, a changed callable, a new test, and a name the expectation also reads (a shared producer moves both sides of the comparison and explains itself). The literal `parametrize` spelling counts too: a vanished live row paired with an arriving live row that keeps the consumed expected cells beside different input cells — but only when the vanished input does not survive with a different answer, which is EXPECTATION_DEFINITION_CHANGED's row-keyed event (#135). Row reorders and pure row additions stay silent. Escalates through repair evidence like every oracle rule, because feeding a test different data is routine when production changed under it |
| `BROAD_EXCEPT_ADDED` | bare `except:` / `except Exception` / empty handler added. In a **test** file only when it swallows an oracle — the guarded block contains an assertion and the handler neither re-raises nor asserts; provoking an error and inspecting it is not suppression. In JS/TS, an assertion the frontend proves always passes (resolved Vitest/Jest expect, node:assert or chai assert; true/false/null subject; matching predicate and polarity; no extra arguments) is not inspection, and its catch reports `catch always-passing assertion`. In Python (#496), a handler that does not re-raise and whose every assertion is proved to always pass is not inspection either, and it reports its first line followed by a space and `[always-passing assertion]`, compared apart from the plain first line: an `assert` of a literal, of `not` before a literal, of a comparison between literals (`is` and `is not` only against `None`), or of `and`/`or` over these with every operand evaluated on its own; or `assertTrue`, `assertFalse`, `assertIsNone`, `assertIsNotNone`, `assertEqual` or `assertNotEqual` with literal operands that pass and at most one literal `msg`, called on a method's own receiver, when the first base of the class's local order that the file does not define has a name ending in `TestCase` and no same-file class before it binds the method's name (D-163). An always-failing assertion stays inspection, and so does any assertion the proof cannot read. |
| `SUPPRESSION_ADDED` | `# noqa` / `# type: ignore` added, in Python files only. No JS/TS form is read: a test file's `@ts-nocheck` is #366, and ESLint directives are #367, deferred by ruling until after 1.0 |
| `CI_WORKFLOW_TOUCHED` | ci-role file changed — pipeline definitions, pytest configuration (`pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini`, `setup.cfg`, `pyproject.toml`), content-classified runner scripts and package manifests whose test command changed (§2), **plus one hop**: a changed script that runs no test runner of its own but invokes another script that does is ci too, resolved against the diff or the head snapshot. Exactly one hop. A shell-script hop must terminate in a real runner — a `ci.sh` calling `compile.sh` stays production, which is the line the content gate has drawn since v0.1.8. A manifest's hop is bounded by where it starts instead: a script that `test` or a `test:*` script names through a script runner is part of the test command whatever it runs, because `npm test` runs `scripts.test` whatever it says (#196 185.2). Test command weakened → high. Weakening is two families, and the difference is the rule's precision. A **swallow** discards an exit code (`\|\| true`, `\|\| :`, `\|\| exit 0`, `set +e`, `continue-on-error: true`): introducing one anywhere is a weakened command. A **narrowing** restricts which tests run (`--ignore`, `--deselect`, `-k`, `python_files`, `python_classes`, `python_functions`, `testpaths`, `norecursedirs`, `collect_ignore`, `-p no:`, and `--test-only`, under which node's runner runs only the tests marked `only` (#196 187.1, #216)): it counts only when the diff *introduces* it — the token must be absent from the base side of every ci-role file in the diff, and the file carrying it must have existed at base. For a package manifest that base side is its base-side test command, not the whole file: a token that only a non-test script carried at base counts once the diff writes it into the test command (#196 185.1). Additionally, literal option/value comparison recognizes newly introduced `--co`/`--collect-only`, `--ignore-glob`, and quoted or unquoted `-k`/`-m` selectors, including a changed value of an existing option. Literal `testpaths` and collection-name lists are narrowing when the new selection is a provable strict subset; additional `norecursedirs` exclusions also count. Restating, reordering or provably broadening a setting is not narrowing it. Identical configuration migration stays quiet, while narrowing during a migration remains visible. First configuration adoption without a base CI surface keeps the syntax scanner at warn; the resolved collection inventory (§2b) still judges a first configuration when it runs. Where it runs, a new root-config selector is judged against the base-suite tests that a run it governs collects: all of them for a run without targets, and those beneath the targets for a run with explicit targets whose discovery finds the same root config on both sides (#196 184.1). `-m`, `-k` and `--co` count whenever such a test exists; `--ignore`, `--ignore-glob` and `--deselect` only when they drop one, and `-p no:` only for a plugin other than `cacheprovider`, `faulthandler`, `pastebin` and `stepwise` (#196 184.2). A positional target in the root config's addopts is an explicit target of every run, read with the one definition of explicit targets a command's arguments use, which knows pytest's own and the common plugins' options that take a value, so `-n auto` or `--cov src` is no target (#173): a run collects beneath its command's targets and the addopts targets together, and when the addopts targets change, a base-suite test the base runs collected and no head run collects is excluded, a weakened command. A target moved between a command and addopts loses nothing. A word in addopts that names no file or directory on its side is no target: it is the value of an option the reader does not know, or a target that fails every run. A head run whose command names a missing path, or that collects no test, fails, and no claim is made for it; ambiguous addopts withholds the inventory. The inventory's settings proof does not reach a run with explicit targets, its command's or its config's addopts'. Also weakening: a tab-indented make recipe prefixed `-` that invokes a runner, and errexit lost between the two sides. Deleting a **workflow** counts as weakening only if that workflow ran tests: a runner name anywhere in it, as row 69 reads one, or a runner site in it, live or dead (#216); deleting a runner script or a config file does not — that is consolidation until proven otherwise. A condition, a trigger, a hook inventory or a GitLab job's keys can stop a runner without touching its line (#181, #214), so GitHub workflows, `.pre-commit-config.yaml` and `.gitlab-ci.yml` are also read as an inventory of **runner sites**, each with whether it can execute for a pull request's commits and fail them. A runner site is a workflow step, a pre-commit hook or a command in a GitLab job's `script:` whose own command invokes a test runner, by a whole-word runner name outside the contexts known not to run it (`echo` and `printf` text, heredoc text written out, install commands, comments; #196 191.5), or by one of the runners #216 adds, `node --test`, `mocha`, `ava`, `tap`, `bun test`, `deno test`, `hatch test`, `just test`, `poe test` and `pdm test`, where a command starts: the first word of a simple command, past assignments, wrappers, package launchers, `sh -c` and `eval`, or inside a command substitution or a heredoc a shell reads, and never as a word elsewhere; or it is a `uses:` step whose action name and one of its `with:` inputs both name a runner. The same reading decides whether a runner-shaped script, a manifest script or a one-hop target invokes a test runner (§2); the opaque-exemption denial (THREATMODEL row 87) keeps row 69's names alone. A site is dead only for a static reason: a step or job `if:` that no event able to run the workflow on a pull request can make true, with status functions read as on an otherwise green run; a job that `needs:` a dead job and has no status function to run anyway; a trigger set with no event that runs on a pull request's commits, including activity `types` without `opened`, `synchronize` or `reopened` and a path filter that leaves no file (#196 191.9, 191.2(d)); a hook parked on the `manual` stage; a GitLab job that does not start by itself on a green pipeline (`when: manual`, `when: never`, or `when: on_failure`) or whose failure is allowed (`allow_failure: true`, or `exit_codes`), where each `rules:` entry that may match decides as the job's own keys do (an entry's condition is not evaluated, an entry with none ends the list, and a job no entry adds is not in the pipeline) and the job's `extends:` templates are merged in first; a hidden GitLab job (`.name`) that no job extends; and every GitLab job when `workflow: rules:` can only keep the pipeline from running (#214). There is no global GitLab token: `allow_failure: true` on a job whose `script:` runs no test runner is not a weakening. A runner command that lost a live site and gained a dead one is a disabled suite, and so is a runner reworded as the inventory moves a site from live to dead (#196 191.8); a pre-commit config whose hook entries invoked a recognised runner at base and invoke none at head, whatever its hook ids and names say, has removed its suite (#196 191.7). Both are weakened test commands. A workflow or `.pre-commit-config.yaml` whose base side the bounded YAML reader read with at least one live runner site, and whose head side it declines, is out of reach rather than weakened: high under E8, with a reason that names what the reader declined and the runner the base side ran (#196 191.3). A workflow is a `.yml` or `.yaml` file beneath `.github/workflows/`, `.gitlab-ci.yml` or `.pre-commit-config.yaml`; any other file kept beneath `.github/workflows/` is ci-role but not a workflow. A ci-role file that carries test obligations (§2) is reported at warn and is not scanned for swallows, narrowings or runner tokens: its lines are test code, judged by the test rules |
| `GUARDRAIL_TOUCHED` | guardrail-role file changed → critical (exception: §6 exemptions). A guardrail file the diff **created** is reported at warn instead: a constraint that did not exist has not been relaxed, and rating creation critical meant `greenwash hook install --agent claude-code` produced a blocking verdict on greenwash's own artefact. Exception to that exception (issue #79): a created `.checkwash/config.toml` / `.greenwash/config.toml` whose content disables any detector or sets `fail_on` above `high` is critical like a modification — with no file the defaults were in force, that file relaxes them, and on the base-side read it governs the next diff, so its creation is the only place the two-commit plant can be caught. A created config that only tightens stays warn; `roles` overrides in a created config stay warn (stated residual)  Since 0.10.0, the D-177 policy-shadow exception: a newly winning `.checkwash/config.toml` over an existing selected BASE `.greenwash/config.toml` compares against that effective BASE policy, not defaults; see §6 policy-shadow transitions. |
| `IMPORT_UNRESOLVED` | new import fails to resolve against lockfile / site-packages |
| `SCOPE_DRIFT` | changed file outside contract globs (disabled without a manifest) |
| `HIDDEN_UNICODE` | zero-width / bidi control characters in changed lines → high |
| `TEST_FILE_UNPARSEABLE` | a test/conftest file greenwash could not parse, so none of its oracles were checked → high if it parsed before this diff |
| `CONFTEST_PATCHES_PROD` | a newly observed conftest patch aimed at repository code or `request.module`. Standard pytest fixture parameters and imported unittest.mock patch APIs are recognized with local binding checks; root/src targets are resolved from strict source snapshots even when production is unchanged. Since issue #85, the builtin `setattr` and the attribute/`vars()` store spellings are recognized when aimed at `request.module` — the one namespace whose writes always rewrite a binding a live assertion reads — while writes to first-party module objects keep the installation trace's execution-proof standard, because they cannot reach a consumer that captured a from-import first. A `getattr`-captured save/restore pair reports once. No rule severity changes. Custom import roots, dynamic wrappers and ancestor/plugin fixture overrides remain unsupported. The source and boundary tests in the issue remediation notes define the bounded coverage. |
| `TEST_PATCHES_SUBJECT` | a test unit that **existed before the diff** now installs a stand-in for something its own assertions check — a newly added `monkeypatch.setattr`/`setitem`, `patch("pkg.mod.attr")`, `patch.object(...)` or `mocker.patch(...)` whose patched **attribute** is reached by the unit's oracle, directly or through **one hop** of the unit's own bindings (`result = billing.total(x)` / `assert result == 105.3`). Three conditions, because inside a test function — unlike in a conftest — patching first-party code is the normal way to isolate a unit: the unit must have existed, the patch must be new, and the patched attribute must be reached. Since issue #88's import sibling, an import that rebinds a captured name to a different live repository provider (`from app.reference import reference_total as invoice_total`, or `import app.twin as billing`) is the import spelling of the same installation; both endpoints must be repository-owned and the old provider must still exist after the diff, so following a deleted module's rename stays silent. Patching a collaborator the oracle never names (a retry delay, a clock, a socket) is hygiene and is not reported, and neither is stdlib or a declared third-party dependency — where "declared" excludes the project's own distribution name, or the check would deny the first party. In JS/TS test files the same three conditions apply to module mocks (vi.mock/jest.mock and their doMock, unstable_mockModule and mock.module forms) and replacing spies, for first-party specifiers only: `./` and `../` inside the repository, an `@/` or `~/` alias (one alias string is one module) and a specifier the base side's root tsconfig.json maps through `compilerOptions.paths`, which names the module at the path it maps to (#196 188.6); other aliases and __mocks__ are residual (THREATMODEL 109). A stand-in a JS setup file installs before every test file is judged as a conftest patch is (#218): a first-party module mock or replacing spy, or `jest.enableAutomock()`, newly written in `setupTests.{js,ts}`, `jest.setup.*`, `vitest.setup.*` or a file the base side's root `package.json` names in `jest.setupFiles`/`jest.setupFilesAfterEnv`, and `"automock": true` newly set under that `package.json`'s `jest` key, is reported with no unit, without resolving which test reads it; runner config files (`jest.config.*`, `vitest.config.*`) stay residual. Escalates through repair evidence like every oracle rule. A target a patcher builds at runtime is read one hop: a name bound once to a string literal, `__name__` (the test module), and an f-string or `+` of those. One that stays unreadable is opaque and counts as reached when the assertions reach its object, or anything at all when that is unknown too. A JS partial factory's merged objects are read one hop the same way, and an unreadable one makes it a whole-module mock (#196 188.5). Residuals: stand-ins installed by a requested fixture, a computed target through a receiver no patcher name spells (`monkeypatch.context()`'s), `respx`/`responses`-style HTTP dialects, two hops, and an attribute named only on a non-literal expectation side |

The unreleased T-326 candidate adds source-backed expectation events under
`EXPECTATION_DEFINITION_CHANGED` for ordinary helper literal actuals and
defaults, helper-local expectations, literal for/unpack tables and changed
fresh-local literal answers. Matching retains the unit, concrete subject/input
and operator, with expected multisets compared separately within each input
key. Existing native and root-helper findings keep their ownership. The
[bounded provenance contract](docs/expected-provenance.md) specifies limits,
unchanged-caller discovery and unsupported control flow. Since #226 the
JavaScript frontend records the same events for an equality whose expected
value reads an import, a declaration or a declared function, and a folded
conversion is its value in both frontends.

An unchanged ordinary assertion retains its native expectation owner; a
callee used only to compute the actual result is not an assertion helper.
The row replacement extension also uses bounded, two-sided syntactic input
roles for an unchanged produced function's evaluated decorator arguments,
and concrete row pairing when an expected cell copies the same active
literal input projection. The surviving-input comparison runs first, and
each disappeared/arrived row occurrence can supply at most one copy witness.
These checks do not prove arbitrary callee dependence or equivalent coverage;
the [parameter input-role contract](docs/param-input-roles.md) records the
exact scope and no-op-callee residual.

The T-326 subject extension adds assignment/native-setattr and literal
dictionary/module installations reaching an existing oracle, including
supported active fixtures and setup hooks. Runtime import-provider changes
use `TEST_PATCHES_SUBJECT` with `unit=None`. Equivalent provider copies remain
silent and grant no production repair credit. The
[subject-integrity contract](docs/subject-integrity.md) defines timing,
first-party ownership, relative package context and complete snapshot APIs;
the older patch-API predicates above retain their own bounds.

All twenty-two are live (thirteen as of M1, `CONFTEST_PATCHES_PROD` as of
v0.1.7, `TEST_PATCHES_SUBJECT` as of v0.1.25), plus one derived rule,
`EXEMPTION_ADDED` (§6). `TEST_DISABLED`
additionally fires when a skip guard's condition, evaluated with each
side's resolved constants, goes from "false somewhere" to "true
everywhere" — the one-line `STRICT = True` → `False` flip that silences a
guarded test without any marker event (probe arm, same day), or an edit of
the guard's own text to one that always holds (THREATMODEL 54). A guard
that reads an attribute through the method's receiver (`self.item_class`)
is evaluated with the value the unit's class body, or a same-file base's,
assigns it (#254 254.Q1). An abstract test base whose skip holds under its
own values keeps no marker when a same-file subclass runs the test
unchanged (254.Q2). It also
fires when a body skip (`pytest.skip`, `pytest.xfail`, `self.skipTest`, or a
raised `unittest.SkipTest` or `pytest.skip.Exception`, in any import spelling:
#220) that ran only under an `if` guard or inside an `except` block runs under
neither: the guard was removed, and nothing is left to evaluate (#196
183.2). A skip in the setup a unit runs carries the condition its setup
reaches it under: each enclosing `if` test, `not (...)` for an `else`
branch and for the code after a branch that always ends, and an `except`
block's condition, with several outcomes joined by `or`. It is judged as a
body skip is, so a setup guard that now always holds, or was removed, is
reported too (183.2's second stage). A function-scoped fixture's guard may
read the requesting unit's static marks first (#358). A path proved false
for that unit is dropped. Visible sources of marks that this reading cannot
resolve keep the guard unknown: fixture params, imported parameter values,
hook bindings, explicit plugin configuration and mutations of test objects,
among others (D-126). Ambient plugins outside the repository snapshot remain
a stated limit; this is not a proof of the complete runtime mark set.
A unit of a test module the diff
changes also reaches the fixtures of every `conftest.py` from the module's
directory up to the repository root, read on each side: the nearest
definition of a name wins, the module's own before every conftest, and a
fixture that requests its own name reaches the next definition outward. A
name the module or a nearer conftest binds some other way (an import, an
assignment, a decorated def that is no plain fixture, a star import) may
hold a fixture there, so the request is followed no further. A conftest
fixture's guarded skip is recorded too (#351). Its top-level constant value
names are expanded before recording; unresolved value names become
`conftest.<name>`. This is partial closure: D6's compatibility-token search
still expands surviving call-target and attribute-root names using the test
module's constants. It is not complete namespace isolation. Imported names
remain unknown, which can permit compatibility credit as well as blocking;
it does not uniformly fail toward flagging. Text expansion is bounded to
4,096 characters per expression and a 65,536-character construction budget
per conftest; exhaustion preserves an unknown guard that earns no credit
(D-127). A suite-level collection control in a
`conftest.py` (§2b) is judged by its guard as well: when that guard could be
false at base and the control has none at head, TEST_DISABLED reports "skip
guard removed of the suite-level control", and the control is unguarded
(#261). A control has none when its guard is removed, when an unguarded
effect or statement joins its guarded ones, or when its guard is a constant
`True` the hook reading drops. Rule-specific notes:

- `TOLERANCE_LOOSENED` direction depends on the tolerance kind: `rel`/`abs`/
  `delta` loosen as they grow; decimal places (unittest's `places`,
  `toBeCloseTo`'s precision) and numpy's `decimal` loosen as they *shrink*.
  Two different kinds that each state an absolute bound are compared as that
  bound, places p as 10^-p/2 written from its digits, in both frontends
  (#196 190.3), and numpy's decimal d as 1.5x10^-d (#222). A tolerance call
  records each tolerance it leaves out at the default its library states,
  except torch's pair, which depends on the dtype and is unknown (#222).
  Unparseable epsilon literals are skipped rather than guessed.
- `EXPECTED_VALUE_HARDCODED` ignores trivial values (None/bools, |int| ≤ 2,
  strings shorter than 3, 0.0/1.0) and any value that already existed on the
  base side — shared vocabulary is not a fingerprint.
- `IMPORT_UNRESOLVED` is **off entirely** when no dependency manifest
  (`pyproject.toml`, `requirements*.txt`, `poetry.lock`, `uv.lock`) is present
  on the base side: with nothing to resolve against, every third-party import
  would look hallucinated. The stdlib baseline is a vendored snapshot
  (`pyenv.py`), never `sys.stdlib_module_names`, so findings do not shift
  between interpreter versions.
- `SCOPE_DRIFT` is off without a task manifest. Only file globs are consulted;
  intent is never parsed.
- `SNAPSHOT_CODE_COCHANGE` requires snapshot + prod change **and** no test
  logic change in the same diff. Any production-role file the diff changes
  counts, a new one included, except a file renamed out of a test, conftest,
  CI, guardrail or snapshot path or out of test collection: that arrives as
  a synthetic addition and is no production change. Test logic in any test
  or conftest file counts: a test unit added in a file that reads no stored
  expectation removes the warning too (#463 Q4 (a); THREATMODEL row 132),
  since checkwash does not know which test reads a stored file.
- `EXPECTED_VALUE_CHANGED` covers the cheat the lattice cannot see: leave the
  assertion's shape alone and edit the expected literal to whatever the buggy
  code returns. It is an oracle rule, so it escalates only when no production
  change explains the edit — legitimate expectation updates travel with one.
- `ASSERT_SUBSTITUTED` exists because assertion identity is positional at the
  last resort. The fallback stage pairs leftovers of compatible strength by
  span order, which is right often enough to be worth keeping and wrong in a
  specific way: two unrelated assertions pair up and the delta describes a
  deletion as an unchanged assertion. It is the only rule keyed on *how* a
  pair was formed rather than on what the pair contains.
- In Python, the fallback stage first gives a test's own old assertion a
  compatible leftover that checks the same subject (#434): the same
  expression read in the same context, either written out, or through a
  local name that only plain `name = <expr>` statements bind, exactly one of
  which reaches the assertion with no conditional one after it, in the
  test's own body. A test parameter, a `global` or `nonlocal` name, and a
  name any other statement binds are read as written, and the names the
  expression reads must have the same reaching bindings on both sides. Among
  such leftovers the same form comes first, then at least the old strength,
  then span order; with none, span order decides. Old assertions are taken in
  span order, and the pair is still a fallback pair. So a precondition
  written above a rewritten oracle on the same subject is added rather than
  paired, and a weakening that still reads the old subject takes the old
  assertion's place ahead of a decoy on another subject in either order. A
  new oracle on another subject against another expectation still pairs by
  span order (#457, THREATMODEL 84b).
- `EXPECTED_VALUE_DERIVED` covers the cheat that survives all three of the
  rules above. Replace the assertion with a *different* one of the same
  strength whose expected side is not a literal: the lattice sees
  `EXACT_VALUE` on both sides so nothing looks weaker, `EXPECTED_VALUE_CHANGED`
  needs both expected sides to be literals, and `SUBJECT_NORMALIZED` needs the
  new subject to contain the old — but the subject never moved. What separates
  it from a refactor is where the new expectation comes from, so the rule
  fires only when the resolved dependencies of the expectation intersect the
  names in the subject.
- `BROAD_EXCEPT_ADDED` is an **oracle** rule when its file is judged as a
  test (§2) or has the conftest role. The detector records these findings
  without a unit, including handlers inside a function; "file-scoped" does
  not mean module-level syntax. A sibling test's symbol evidence never
  reaches such a finding. In a Python file, a finding with no unit now
  refuses clause 3's opaque production credit (D-176). In JS/TS, that credit
  is unchanged pending #212. The broad five-rule refusal introduced by #464
  remains disabled under D-171; this revision admits only the separately
  stated Python broad-except condition. Production-role handlers that carry
  no test obligations remain non-oracle findings.

## 4b. Artifacts are never evidence

Generated and binary paths (`__pycache__/`, `.pyc/.so/.dll`, `dist/`,
`build/`, `.pytest_cache/`, `node_modules/`, images, archives, …) are dropped
from the diff before analysis. They cannot produce findings and, critically,
cannot grant repair evidence: pytest's own untracked `.pyc` output was enough
to disarm E1 for an entire diff, which any build artifact in any repo would
have reproduced.

Matching is **path-segment anchored**, never substring. Bare substrings made
`build/` match `mybuild/` and `dist/` match `redist/`, which silently deleted
real source trees from the analysis and made a directory rename a bypass.

A changed side over the 1,000,000-byte source limit is unread. The run exits 2, naming path, side, size and limit, when a detector must read the path; §9 says what `--format json` prints then, and what `check --format hook-json` reports instead. Such paths are test, conftest, CI, guardrail, snapshot, JS test and setup, runner-shaped, test-command, out-of-scope and root `scripts/` files, any Python module and any pytest configuration. One bounded read answers the runner-shape question of §2 for an unread side: its first 200 bytes, the only bytes the shell-shebang test reads, kept from the working-tree read or streamed from Git and checked against the blob's object id. A side whose bytes start with a shell shebang makes its path runner-shaped, as §2 reads a shebang, whatever its suffix, and the refusal names that side; as in §2, a Python module or a JS/TS test path is never runner-shaped, and refuses by its own rule. A file with no extension no longer refuses for the shebang it may hold, except when a side's bytes were not read, as for a Git side over 64,000,000 bytes, which is not streamed; another rule above can still make it a path a detector must read. Those bytes answer nothing else: they reach no parser, no runner-content check and no repair evidence, and no output carries them. The run also refuses in the same way when the analysis reads the path as context; the runtime-provider pass does not read a dropped path for a shebang its bytes have ruled out. Otherwise the change is dropped: no findings, no repair evidence. An oversized root `poetry.lock` or `uv.lock` at the base is skipped with a stderr note. The managed PreToolUse hook (§9, D-189) neither refuses nor drops: when either side of its one change, the working-tree copy or the proposed bytes, is over the limit, it asks, naming path, side, size and limit, since padding a test past the limit and editing the padding away would otherwise pass unseen; the Stop hook blocks on a head or worktree side for the same reason (#456).

## 4c. The task contract is base-side too

`--task` carries `oracle_freeze` and the scope globs, i.e. two escalators. It
is therefore read from the **base** side like config and the allowlist (§1);
the working-tree copy is a fallback only at the root, for a task file the
base tree does not hold (below). Otherwise a diff could edit TASK.md to
disarm E2 and E7 for itself.

The managed PreToolUse hook (§9, D-189) reads no `--task`. It forces
`oracle_freeze` on for its one change, whatever a task file says, so E2
applies there, and it applies no scope globs, so its change gives no
`SCOPE_DRIFT` and no E7.

Let R be the directory originally named by `--repo` (default `.`), interpreted
natively relative to invocation cwd if R is relative. Compute
`T = os.path.abspath(os.path.join(R, args.task))` once for lookup. Relative
`--task` therefore belongs to the originally named directory, before Git
re-roots the review; it is not independently resolved against cwd or the
re-rooted Git root. From a subdirectory map T relative to R, prepend Git's
`--show-prefix`, and collapse `.`/`..` lexically. At the root map T relative
to the repository address. Never call realpath or resolve a HEAD-side task
alias to select a BASE contract.

Native address rules remain load-bearing: a fully-qualified path supplies
its own address; on Windows a root-relative task takes its drive/share from
R and a same-drive `C:TASK.md` joins R. These are native lexical operations,
not an implicit drive/share mount or alias-canonicalization feature.
A native relpath failure remains an engine error; it cannot activate fallback.

Read the mapped BASE path even if HEAD rewrites either contract. From a
subdirectory a BASE miss remains an engine error under #416. At the root,
#500's case-insensitive task spelling/proper-prefix checks still refuse an
existing BASE file, symlink or gitlink that the requested disk spelling can
stand for. Only genuine BASE absence permits opening T from the worktree,
with the existing disclosure that the change controls that fallback. It is
not necessary that the path be untracked. The permitted fallback may still
be followed by the OS; it is never used to rescue a refused BASE alias.

### TASK policy syntax validation (0.10.0, D-181)

Authority readers validate the restricted front-matter subset before applying
any TASK contract. BASE bytes require strict UTF-8 decoding; NUL text refuses
instead of silently treating UTF-16-like input as an absent contract.
Recognized unsupported forms (including BOM, an unclosed
front matter, commented/indented contract headers, noncanonical booleans,
inline scope/list forms and trailing scope comments) are engine errors rather
than advisory-only partial policies. Duplicate blocks/fields, unknown or
misplaced fields within a recognized block, malformed glob quoting and
inconsistent field/list nesting also refuse. The error names the TASK source
and explains that no TASK policy was applied. Existing engine-error projection
applies: exit 2 for term/JSON/SARIF and NOT_ANALYSED for the Stop hook (§9).

Canonical block forms, the legacy greenwash header, case-insensitive bare
true/false, literal fully quoted globs, unrelated front-matter metadata,
ordinary prose and existing empty-scope semantics remain. This is validation,
not general YAML support. `load_contract` is the authority API. The historical
best-effort `parse_contract` decoder remains for old case records and must not
be used to load an unvalidated policy for review.

### Textual worktree relocation (0.10.0, D-182)

Worktree delete/add pairing accepts exact bytes or UTF-8 text differing only
by CRLF versus LF. It retains the original before/after bytes in the change;
it does not normalize fingerprint evidence or read additional paths. Binary
NUL content and invalid UTF-8 require byte equality. Lone CR, whitespace and
content edits are not equivalent. Equal-content ties retain the existing
lexical, single-use pairing. Range mode still uses Git similarity; this is
not a general claim that all range/worktree rename classifications coincide.

## 5. Escalators / de-escalators (applied in order, all deterministic)

| id | condition | effect |
|---|---|---|
| E1 `NO_PROD_CHANGE_IN_DIFF` | oracle finding with **no repair evidence** (defined below) that no de-escalator below holds. The id stays E1; the label is chosen in this order. A blocking unguarded conftest suite control in a diff that changes any production-role file is labelled `COLLECTION_CONTROL_UNEXPLAINED` (§4). Otherwise, a finding matching the separately admitted Python unit-less `BROAD_EXCEPT_ADDED` condition is labelled `OPAQUE_PROD_CHANGE_NOT_EVIDENCE` when `prod_opaque_change` is true. Otherwise, a diff that changes a production-role file (§2) other than the inert files of clause 3 below gives `PROD_CHANGE_NOT_EVIDENCE`: production changed, and no evidence the finding may take reaches that change, as when the test reaches it only through an unchanged module (#473). That production-role file can be one checkwash reads no symbols from: a file that stops parsing, a non-Python file the diff adds, deletes or renames, or one whose content runs a test runner. Generated artifacts and a change set aside unread (§4b) are no production-role change. Every other such finding, in a diff that changes no production-role file or only inert ones, is labelled `NO_PROD_CHANGE_IN_DIFF`. The broad five-rule refusal set remains empty. The label is chosen after severity and remains outside the fingerprint. The label itself changes no severity, verdict or fingerprint; the new refusal of repair credit can change severity and verdict | warn → high |
| E2 `ORACLE_FREEZE` | contract declares `oracle_freeze: true`, or the managed PreToolUse hook forces it (§4c, D-189) | warn → high |
| E3 `HARDCODE_FINGERPRINT` | **Retired** (#419, D-141). Nothing implements it: `EXPECTED_VALUE_HARDCODED` is an oracle rule and goes through E1 and D1 like the others (`gating.py` `ORACLE_RULES`; `expected_hardcoded_pos` pins warn with `REPAIR_EVIDENCE`) | none |
| E4 `META` | guardrail / greenwash-own-config touched | → critical |
| E5 `HIDDEN_CONTROL_CHARS` | `HIDDEN_UNICODE` hit | → high |
| E6 `CI_TEST_COMMAND_WEAKENED` | CI diff weakens the test command as defined in §4 `CI_WORKFLOW_TOUCHED` | → high |
| E7 `OUT_OF_SCOPE_PROD_TOUCH` | `SCOPE_DRIFT` onto a prod / ci / guardrail file. E7 reads a test role that comes from the path alone (a JS/TS test path, or a file beneath a test-support directory, §2) only when the file declares a test on either side; otherwise it reads the role the §2 table and runner promotion give the path, so production code named like a test is a production touch (#196 186.8), and so is test data or a manual mock (#217). Every other rule keeps the test role | → high |
| E8 `CI_BECAME_UNANALYSABLE` | a workflow or `.pre-commit-config.yaml` whose base side the bounded YAML reader (§4 `CI_WORKFLOW_TOUCHED`) read with at least one live runner site, and whose head side it declines. E6 still applies when the same file also weakens a test command (#196 191.3) | → high |
| D1 `REPAIR_EVIDENCE` | repair evidence exists | hold at warn |
| D2 `ASSERTION_MOVED` | a removed oracle has a matching two-sided static context in a live arrival, under D-179 below. Text, body hash, assertion mass and name similarity alone establish no credit. Existing collection/liveness checks remain. Each arriving assertion is spendable once across whole-unit, assertion and D5 routes; a complete-unit credit consumes its assertion credits too. Complete-unit equivalence may return at info; assertion-only credit still applies E2 under oracle_freeze | info, or high/ORACLE_FREEZE for assertion-only credit under freeze |
| D3 allowlist hit | valid exemption in base-side `allow.toml` | suppressed (still listed in report footer) |
| D4 `SAME_UNIT_REWRITE` | a removal is escorted by a **newly written** assertion of strength ≥ PATTERN in the same unit | hold at warn |
| D5 `RESTRUCTURED` | within-file oracle mass is a candidate budget only; every lost own assertion must also have a matching static context/multiplicity proof in live arrivals (D-179). Split/renamed candidates use the same proof and shared spendable budget | hold at warn, still subject to E2 |
| D6 `COMPAT_GATE` | the added skip is a `skipif` or a non-strict `xfail` mark (on the test, on its class, or in a `pytestmark`, which is read as the call it holds: #209 X1), a skip or non-strict `xfail` mark that a `pytestmark` binding carries under recorded guards, judged on the guard and the mark's own condition together (#260 Q2: `if sys.platform == "win32": pytestmark = pytest.mark.skip(...)` holds as its `skipif` spelling does), or an imperative skip (`pytest.skip` / `pytest.xfail` / `self.skipTest`, or a raised `unittest.SkipTest` / `pytest.skip.Exception`, in any import spelling: #220) under recorded `if` guards, in the test body, in the setup the unit runs (#196 183.2), or in a helper either of them calls, same-file or imported (#272). So is a later binding of the test's name that may replace it (`collection.rebound`, §2b), under the condition that binding runs under; one with no condition D6 can read (a loop body, an `except … as` or for target, a `match` case, mid-way through a `try` body) earns nothing (#424). A mark's condition given as a string is the expression pytest compiles from it, read as pytest evaluates it: `os`, `sys` and `platform` are those modules unless the test module binds the name to a constant, and `config` is unknown; a string that does not compile earns nothing (#263). Its condition — with module constants resolved from the test file, from files in the diff, or from the head snapshot — must reference the interpreter/OS environment (`sys.version_info` / `sys.platform` / `platform.` / `os.name`, in the condition text or in a resolved constant), and, **evaluated** over a matrix of supported Python versions and platforms, must not be provably true everywhere. "True" means truthy: a condition that is always truthy is an unconditional kill in a compat costume. Sub-expressions that cannot be resolved stay unknown, and credit is denied only when the condition is true under every assignment of the unknowns; `strict=True` xfail earns nothing (it inverts the oracle instead of skipping it). A suite-level collection control in a `conftest.py` (`collect_ignore`, a collection hook, an `add_marker(...skip)` in one; §2b) is judged on its own guard, which need not name the interpreter or OS but must be able to be false (D-028, #209 Q1). The hold is a fact about the marker the finding reports: every after-side marker of that name must qualify, and a finding with no marker of its own (a unit gone, parametrize rows deleted, a guard weakened or removed) gets none, so a gate lends nothing to another disable on its unit (#208) | hold at warn |
| D7 `MILD_WEAKENING` | `ASSERT_WEAKENED` that fell < 30 points and landed ≥ EXACT_VALUE — still inside the exact family; landing at APPROX or below is material (THREATMODEL 13), so 90→70 and 70→60 are not mild | hold at warn |
| D8 `PROD_SYMBOL_REMOVED` | a `TEST_DISABLED` in its removal shapes only — a unit that disappeared outright, or deleted parametrize rows; never an added marker — while the same diff deletes a prod symbol that existed at base **and whose enclosing scope is gone too** (a rewritten function "deletes" its old locals, and that counts for nothing), in a module the test file's imports reach (or, failing that, whose leaf name matches the `test_<module>` / `<module>_test` filename convention). Feature removal explains the removal of its test; new code explains nothing | hold at warn |
| D5 `SAME_UNIT_REWRITE` (extended) | an `ASSERT_SUBSTITUTED` in a unit that also **deleted** an assertion and **wrote a new strong one** — the private-API-to-public-API rewrite cluster. Crediting the removal at warn while blocking the substitution at high described one edit two ways. A pure substitution removes nothing, so the shape this rule exists for is untouched | hold at warn |
| D9 `DEPENDENCY_DRIFT` | an `EXPECTED_VALUE_CHANGED`, an `ASSERT_SUBSTITUTED` or an `EXPECTATION_DEFINITION_CHANGED` — those three only; `PACKAGE_REPAIR` (below) takes the first and the third — while the same diff changes a dependency manifest (`pyproject.toml`, `requirements*.txt`, lockfiles). A manifest counts only when its **dependencies** differ: a project's own `version =` line is dropped before the comparison, because otherwise every release commit buys the credit with its own version bump — the diff that motivated `ASSERT_SUBSTITUTED` bumps `version` in `pyproject.toml` and was de-escalated to warn by it. A pinned dependency's behaviour change is the honest cause of expectation drift, and it moves *how you reach* a value as often as the value itself — flask's `bump werkzeug 2.3.7` commits rewrote `rv.data == b"127.0.0.1"` into `flask.g.remote_addr == "127.0.0.1"` with the oracle intact. A manifest bump buys nothing for a weakened or deleted oracle, and all three credited rules require unweakened strength (an `EXPECTATION_DEFINITION_CHANGED` assertion's text is unchanged) | hold at warn |
| D10 `DUPLICATE_REMAINS` | a disappeared unit has a proven complete oracle-context equivalent in an unchanged, live, collectable Python survivor. The existing bounded head search (at most eight parsed candidates), conftest liveness (#266) and collection checks remain. Strict startup context is required; an unknown context earns no credit. A verified survivor is reusable for genuine deduplication. JS/TS survivors remain outside this route (#484) | → info |

D4–D7 came from triaging 48 real blocked commits in OSS history
(`benchmarks/triage-2026-07-30.json`). D8–D10 came from the second
adjudication pass (`benchmarks/adjudication-2026-08-03.json`): feature
removals, dependency drift and duplicate cleanups were the largest honest
clusters among the 28 remaining false positives. Two design notes that are
load-bearing:

- **D4 requires the replacement to be newly written.** A unit that merely
  *keeps* an existing assertion while the inconvenient one disappears is the
  sacrificial-cheat signature and must keep blocking. Normalized text
  comparison against the before side is what separates the two.
- **Oracle mass** (D5) = strong assertions × parametrize row count. Merging N
  tests into one parametrized test preserves mass; deleting N tests does not.
- **A strong assertion must be able to fail.** Everywhere compensation is
  counted (D4, D5, split/rename), an assertion qualifies only if its strength
  is ≥ PATTERN *and* its subject depends on something other than literals and
  builtins. `assert str(1) == "1"` sits at EXACT_VALUE and is vacuous; one
  such padding line could launder a whole file of deleted oracles.
  "Depends on a variable" is necessary but not sufficient: shapes that are
  true for every possible input — `assert "" in str(x)`, `assert len(x) >= 0`,
  `assert (cond, "msg")`, `assert isinstance(x, object)` — are TAUTOLOGY, so
  they never count. The list is a floor, not a completeness claim.
- **Split/rename needs mass, not just a name.** A disappeared unit is excused
  as split-or-renamed only when a related name arrived *and* the file's added
  oracle mass covers what it lost. Name similarity alone let one weak survivor
  excuse every deleted test in the file.
- **An assertion reached through a helper method earns nothing for another
  finding** (#306). A `via` assertion (§3) counts in no D2 move credit, no
  D5 oracle mass, no D4 newly written assertion and no split/rename budget,
  and a disappeared unit needs none of its `via` assertions moved. A finding
  about a `via` assertion takes the credits a module helper's inherited
  assertion takes.

None of D4–D10 suppress a finding. They only decline to *escalate* it: the
finding stays in the report (D10, like D2, at `info`; the rest at `warn`),
visible and allowlistable.

**Repair evidence** answers one question — is there a production change that
plausibly explains editing *this* test? E1 and D1 are the two sides of it: D1
holds an oracle finding that has evidence, and E1 escalates one that has none
and that no other de-escalator holds. Evidence exists when:

1. the normalized AST fingerprint of a symbol the test calls changed, which is
   not a behaviour change: docstrings are stripped, and
   `_normalize_for_fingerprint` drops annotations, non-leading string
   statements, value-less annotated assignments and function-local dead
   literal bindings. Any other edit counts, an alpha-rename, `+ 0`, a
   single-use temporary or a dead branch included (THREATMODEL 93, #419).
   For a finding about an assertion that reads the value of a fixture the
   test requests, the call that fixture returns or yields counts as a symbol
   the test calls (the fixture's producer, below; #471), or
2. a symbol the test calls itself calls a changed symbol (one hop — a test
   going through `format_invoice` is legitimately updated when the
   `compute_total` it calls changes); a changed symbol that a same-file
   helper the test invokes calls counts too (a top-level function of the
   test module that is neither a test nor a fixture; the T1.9 hop), for
   every oracle finding but `TEST_DISABLED`; for a finding about an
   assertion the test reaches through a helper method (§3), a symbol that
   method calls counts too, and for no other finding (#306), or
3. the diff **modifies** an existing production file checkwash cannot
   analyse: code in another language, a template, a data file, or Python that
   did not parse at base — conservative, see THREATMODEL #4. The inert files
   (`roles.py`: type stubs, docs-site config, repo metadata), generated
   artifacts (§4b), files beneath a test-support directory and files whose
   content runs a test runner (§2) are not such files. A deletion does not
   count, and neither does unparseability the diff causes: a production `.py`
   that parsed at base and does not parse at head is reported unparseable
   instead (THREATMODEL 78, 80). A path renamed onto production from one that
   was not production is not pre-existing production (row 79). A file the
   diff *adds* does not count: it cannot be the repair of behaviour that
   predates it, and a genuinely new implementation arrives with the Python
   that reaches it. Told to defeat this tool and handed its source, an agent
   wrote a three-line json file nothing imports, purely to satisfy this
   clause (row 73).
   Every oracle finding takes this clause except an unguarded suite control
   (§4, THREATMODEL 72) and a `BROAD_EXCEPT_ADDED` finding with no unit in a
   Python file judged as a test (§2) or holding the conftest role (D-176).
   The latter condition refuses this credit for comment-only and substantive
   opaque modifications alike; it does not prove that the modification is
   irrelevant or dishonest. All other rules retain D-171's refusal-off
   behavior, including Python unit-scoped weakening, removal, disabling and
   tolerance findings. #419 remains open for those routes and for Route A;
   JS/TS behavior and #212's ruling remain independent.

**A fixture's producer** (#471). A test that gets its subject from a pytest
fixture calls nothing that builds it, so clause 1 counts one call of the
fixture as the test's:

- **The producer** is the call whose value the fixture returns or yields:
  its only `return <value>`, or in a generator its only `yield <value>`,
  directly (`return C(...)`, `yield C(...)`) or through one plain local
  binding (`p = C(...)`, then `yield p`). A single `return` or `yield` that
  runs only under a branch, a loop or a `match`, or in a `try`'s handler,
  `else` or `finally`, gives no producer. The other calls in its body, the
  producer's own arguments included, do not count. The producer is matched
  as a call of the test is (clause 1, with the D-046 module check), against
  the modules that the import binding its root names in the fixture's own
  file, not the test file's imports. A root the fixture binds itself, as a
  parameter (`return app.test_client()`) or a local, gives no producer, and
  so does a root whose final top-level binding in that file is not an
  `import` or an absolute `from ... import` outside any `if` or `try`, or is
  followed by a star import.
- **One level.** Only a fixture the test requests by parameter (an argument
  without a default, `request` and the instance excepted), resolved as
  pytest resolves it for that test: the innermost class, then the enclosing
  classes and the module, then each `conftest.py` above the module, nearest
  first. A name a `parametrize` supplies directly runs no fixture. A level
  that binds the name some other way, a star import, an unreadable
  `conftest.py`, or a class with a base other than `object` or a keyword
  stops the lookup with no producer. The fixtures a fixture requests count
  nothing, and so do an `autouse` fixture and a `usefixtures` mark that the
  test does not also request by parameter.
- **Only the findings whose before-side assertion reads the fixture's
  value.** The assertion is the one the finding cites on its before side,
  or the before half of the pair whose after side it cites
  (`EXPECTED_VALUE_HARDCODED`). It reads the parameter directly or through
  the test's own assignments, written in the test's body outside a nested
  def, class or lambda, and the test does not bind the parameter again (an
  assignment, a `for` or comprehension target, `with ... as`,
  `except ... as`, `del`, an import or a nested def). The fixture is
  resolved and read as the test module and its `conftest.py` files were
  before the diff. A finding that cites no assertion of the unit (a unit
  gone, `TEST_PATCHES_SUBJECT`, a tolerance change) takes nothing.
- **Every oracle rule that takes symbol evidence, except `TEST_DISABLED`**,
  as for the T1.9 hop; `TOLERANCE_LOOSENED` takes nothing in practice, as
  its finding cites no assertion. Neither the one-hop route of clause 2 nor
  a helper hop is followed from a producer, and no package-level credit is
  added. Both limits depart from the analysis the ruling adopted, and the
  owner kept both on 2026-10-19 (D-155).

`EXPECTED_VALUE_CHANGED` additionally accepts **package-level** evidence
(`PACKAGE_REPAIR`): the test file imports a package in which the diff changed
production code. Symbol evidence is built only from files the diff touched,
so it cannot see through an unchanged intermediate module — a test calling
`httpx.URL(...)` earns nothing from a fix in `httpx/_urlparse.py` behind an
unchanged `_urls.py`. That single blind spot was 13 of httpx's 20 blocked
commits. It is scoped deliberately, to this rule and to
`EXPECTATION_DEFINITION_CHANGED` (§4): a test-only diff changes no production
package at all, so it cannot excuse the cheat the rule exists to catch.

Evidence is deliberately **not** "some prod file in this diff changed". That
diff-global test let a single dead constant, a statement reorder, or an edit
to an unrelated function disarm the gate for the whole run.

### Oracle-context proof in IR3 (D-179, 0.10.0)

Python relocation proof includes module/import/class context, full decorators
and arguments, parameter inputs/expectations, the assertion's prior/following
execution context, conftest startup and ancestor package initializers. Unknown
assertion calls are retained; only proved pure literal assertions may be inert.
Literal parameter combinations are expanded statically up to 64 live rows.
There is no getattr-to-attribute equivalence: opaque prior calls may replace
builtin lookup. Module/helper metadata and unsupported dynamic contexts supply
no proof. Exact complete-unit relocation remains available with known context.

JS/TS proof retains declarations/tables, bindings and surrounding execution.
Ordinary strings are never module paths. Only recognized static import tokens
may be resolved lexically; bare, dynamic or unknown imports retain their
directory context. Existing runner/liveness admission is unchanged.

IR3 adds optional UnitSide.oracle_context and oracle_assertion_contexts. Empty,
missing or malformed proof is unknown; valid values are lowercase SHA256 keys.
Assertion keys are IDs with an optional @row ordinal. duplicate_unit_hashes now
contains complete oracle-context keys; moved text/body lists are candidates,
never authority on their own. Historical IR2 gains no inferred proof. Finding
envelope2 and existing fingerprint formulas stay unchanged.

Optional proof is bounded to 256 KiB/128 units per file, 16,384 module AST nodes,
128 statements/4,096 nodes per function, and bounded startup reads (16 ancestor
levels, 64 initializer records, 64 KiB each). Missing/read/type/size/budget or
resource gaps withhold compensation without skipping ordinary analysis. Stable
AST keys omit only empty type_params and reject unsupported generic syntax.

This is bounded static obligation matching, not universal runtime equivalence.
External plugins/import hooks and unsupported dynamic behavior remain limits.
D1/D3, same-unit rewrites, compatibility/production-removal policy, strength and
alignment retain their separate contracts. Complete-unit/duplicate equivalence
can retain info under freeze; every assertion-only D2 or D5 route still reaches
E2. Exact eligible BASE exemptions retain priority. The original eight golden
expectations were unresolved compatibility failures at the initial integration.
The later delegated dispositions in D-185 preserve their old bytes and migrate
their expectations to the retained blocking obligations; they do not restore
text-only credit. See docs/oracle-context-dispositions-0.10.0.md.

## 6. Exemptions

### Quality policy maintenance (D-180)

Main and quality exemption lanes are independent. Edits of existing quality
policy/allow files retain main's guardrail review. Quality `reported`/0 can
include policy warnings and is not a main-check pass. Only eligible entries
in the selected BASE quality policy/ledger can affect that quality comparison;
new HEAD entries and tool-generated ownership claims grant no authority.
Precise maintenance uses the existing prior-BASE review route, without a
blanket quality-path exception or automatic main/quality key translation.

### Policy-shadow transitions (0.10.0, D-177)

Existing guardrail edits remain critical, except for the append-only ledger
case below. When no effective BASE predecessor exists, the existing fresh-file
defaults comparison remains in force. Inactive lower-priority creations keep
their existing treatment. A newly created `.checkwash/config.toml` that becomes
selected over an existing BASE `.greenwash/config.toml` compares with that
effective BASE config, including an existing zero-byte file; absence is None.

- A new disabled-rule name, a rise in the `fail_on` severity threshold, or
  `on_engine_error: block` becoming `pass_with_warning` makes the new config
  critical.
- If both policies parse without warnings, their role tables are equal, the
  new disable set is a subset of the old one, its threshold does not rise and
  its engine-error policy does not weaken, the created config stays warn.
  Equal-policy copies and this bounded tightening are included; arbitrary
  glob-language inclusion is not inferred.
- Parse errors, value warnings or differing role tables make the transition
  uncomparable and critical. This is a conservative maintenance cost, not a
  proof of malicious intent. Existing loader exceptions remain engine errors.
- Config and allow precedence remain independent by filename. Evaluation
  uses selected BASE policy throughout the reviewed diff.

A newly created `.checkwash/allow.toml` selected over an existing BASE
`.greenwash/allow.toml` uses the effective BASE ledger for the existing parsed
entry prefix comparison. An equal ledger adds no entries. A preserved prefix
followed by new records emits EXEMPTION_ADDED only for that suffix. Rewriting
or removing an existing record, including an empty priority file hiding a
nonempty BASE ledger, is GUARDRAIL_TOUCHED critical even though the priority
file is new. Revocation therefore retains its protected maintenance cost even
when it tightens the gate. The parser's existing ignored-record behavior is
unchanged.

Shadow GUARDRAIL_TOUCHED fingerprints keep their content-bound v2 outer form
and additionally bind the selected BASE policy's fixed repository-relative
path, complete raw-byte SHA256 and bounded transition kind. Physical before
and after identity remains bound. Exact keys move; old approvals require
review and are not automatically translated. EXEMPTION_ADDED keeps its key
formula for actual suffix additions; duplicate visibility for migrated records
disappears.

IR3 requires `globals.policy_shadows` in every payload, including an empty map
when none is reported. Each entry has exactly `base_path`, `base_sha256` and
`kind`; no policy values or arbitrary paths are copied. This required proof
slot is why IR_VERSION is 3; an omitted slot is not proof of no shadow. Old IR2
documents remain IR2 without inferred proof. FINDINGS_VERSION remains 2, as
does its envelope/object field set. Exit meanings remain 0 pass, 1 block and
2 engine error.

CLI and sweep pass selected BASE path/raw bytes they already read, without a
new HEAD authority read or widened source admission. Direct build_ir/analyze
callers creating a priority policy file need PolicyBase provenance for that
filename, including known absence where applicable. Missing relevant proof
refuses with EngineError. Closed .gwcase adapters use explicit before policy
bytes; after-only means absent at BASE. HEAD-only or slash-alias-ambiguous
context remains unknown by filename through known_names and refuses only when
that filename's new priority creation needs it. An unrelated unknown allow
context does not refuse config creation or a test-only change, and vice versa.
The engine's lexical backslash-to-slash spelling applies before membership,
filename and suffix comparisons and to policy mapping/case keys. No case-fold,
dot resolution, realpath or filesystem authority is added. case_snapshot is
AFTER content and never supplies BASE authority. Golden/demo callers still
pass allow_entries=[]; fixture ledger bytes never activate exemptions.

This contract does not change directory precedence, existing-file/Git-rename
policy, copy-plus-delete maintenance, arbitrary role-glob ordering, HEAD-only
exemption authority, the historical single exemption_ledger_path attribution,
BASE roles already excluding guardrails, reader admission or hook error rules.
The implementation was authorized under Nelson's 2026-10-27 pre-1.0 repair
instruction. Version metadata and this contract are not release qualification
or publication evidence; stop for Nelson's decision before 1.0.

`.greenwash/allow.toml`, per-fingerprint only (never per-rule):

```toml
[[allow]]
fingerprint = "ASSERT_WEAKENED/tests/test_billing.py/test_total/v2:37f08a9259e7ed09de22a72c46a0f36042da9710d7db47f91c5c1ad72bc93d67"
rule = "ASSERT_WEAKENED"
reason = "behaviour change #482: totals now tax-inclusive; replaced by range+property tests"
author = "alice"
created = "2026-07-29"
expires = "2026-10-01"
```

- `reason` and `expires` required; `expires` at most 180 days out.
- In the managed Stop hook with a recorded session, the base side is the
  session base (§1, §9), so an entry committed during a session applies from
  the next session.
- The managed PreToolUse hook (§9, D-189) reads `allow.toml` from the session
  base when a usable record exists, else from HEAD. Its fingerprints are
  computed on its own one change, the working-tree copy against the proposed
  bytes, so an entry recorded from a CI run or a Stop hook, whose before side
  is a commit, may not match an edit to a file already edited in the session;
  that edit is then asked about.
- Evaluation reads the **base** side. However, **append-only, schema-valid
  additions** to `allow.toml` in the head side do not trigger
  `GUARDRAIL_TOUCHED`(critical); they produce a prominent `EXEMPTION_ADDED`
  finding pinned at the top of the report ("this PR exempts itself: N entries
  — review them"). Modifying or deleting existing entries stays critical.
  Deterrence comes from visibility, not from welding the escape hatch shut.
- Expiry comparison uses `GREENWASH_TODAY` (ISO date) if set — tests and CI
  pin it — else the current date. This is the only clock read that can affect
  a verdict, and it is overridable precisely so runs can be reproduced.

Except for the content-bound forms described below, fingerprint remains
`sha256(rule + "/" + path + "/" + qualname + "/" + normalize(before_text))[:12]`,
prefixed `rule/path/qualname/` for readability. That legacy normalization
strips whitespace outside string literals and preserves whitespace within
them; line numbers are excluded. Since #421 and #512 this legacy form is the
key of EXPECTED_VALUE_HARDCODED, CONFTEST_PATCHES_PROD, TEST_PATCHES_SUBJECT
and the rules that are not oracle rules; for those, one approval still covers
any after state of the same before text.

ASSERT_WEAKENED, ASSERT_SUBSTITUTED, ASSERT_REMOVED, TOLERANCE_LOOSENED,
EXPECTED_VALUE_CHANGED (assertion level), EXPECTED_VALUE_DERIVED,
EXPECTATION_DEFINITION_CHANGED (both emitters), SUBJECT_NORMALIZED and
SUBJECT_INPUT_CHANGED (both forms) use assertion-level content-bound v2
fingerprints (#421), emitted as `rule/path/qualname/v2:<64hex>`. A JS
qualname is the raw test title and may hold `/`, even last; only the last
segment is read as the digest. The digest is the complete SHA256 of ASCII canonical JSON (sorted keys, compact
separators) of an identity under the scheme name
`checkwash/assertion-fingerprint/v2`. The identity holds:

- the rule, path and qualname;
- the exact legacy pre-image, `rule/path/qualname/normalize(text)` with the
  text the legacy key hashed, so every v2 key refines its legacy key;
- the complete before and after assertion texts, null for an absent side;
- the event kind (for ASSERT_WEAKENED: unbindable operands, an unreadable
  tolerance, a predicate relation, a polarity change, or a strength drop);
- the ordinal and the count of the before side's assertions with the same
  text, in the unit's own order (its own and same-file assertions in source
  order, the copies of one helper assertion in the order of their call
  sites, then those from other files), so identical copies are separate
  approvals;
- the rule's context: the tolerance kind with both recorded values; for
  each name whose definition moved under an unchanged expectation, its
  recorded definitions (reaching definition, local binding, parametrize
  column and rows, module constant, same-file fixture), before and after;
  the changed subject inputs; the resolved subjects of a normalization, in
  the same normal form as the texts; the names a derived expectation shares
  with the subject.

Texts use the legacy normalization, except that a JavaScript template
literal is kept as written, since it is the literal's value, and the code of
each `${...}` in it is normalized as code; pairing and move detection keep
the legacy form. Spans, line numbers,
messages, strengths, severities, file digests and revision labels are
excluded, so reformatting outside string literals and moving the line keep
the key. A set (a literal argument or table cell) is encoded as a list in
sorted order, so the key does not depend on the hash seed. Computing the
identity never raises: an input that cannot be read is null, and so is a
context that cannot be encoded. A different after on
the same before, another copy of the same assertion, or a different relevant
context requires a different approval.

TEST_DISABLED uses the same form since #512, `TEST_DISABLED/path/qualname/v2:<64hex>`,
a focus a diff adds to a file under the qualname `<file>`, with the same
scheme name and encoding. Its identity holds the legacy pre-image unchanged
(the text the legacy key hashed: the marker's name, `guard:<marker>`,
`parametrize`, a removed unit's own assertions in the legacy text form or
its name when it has none, or the focus marker's name), the finding's
`shape` as the event kind, no ordinal or count, and what that shape
changed:

- a marker added (`marker_added`, `collection_control`, and `inert_mark` for
  a conftest's `pytestmark`): the marker's complete text as the after text,
  and its recorded guard as the context, null when it has none, so where the
  frontend records the guard, as the Python frontend does, a guarded skip
  and an unguarded one of the same name are two approvals; a JS/TS
  imperative skip (`ctx.skip()`, `t.skip()`, `this.skip()`) records none, so
  for it they are one. Alignment records only the names of the markers it
  leaves unpaired, so the markers a name added are read by content: each
  base marker of that name cancels one head marker of that name with the
  same text and guard, and the head markers left over, in the head side's
  order, are the ones added. When there are as many of them as the name has
  findings, each finding binds one of them, in that order. Otherwise (a
  marker of that name also edited, one moved in from a helper, or one paired
  with a marker of another name) each finding of the name binds, as the
  context, every marker of the unit on both sides, each a name, text and
  guard, each side sorted;
- a guard made always true or removed (`guard_weakened`, or `inert_mark` in a
  conftest): the guard before and the guard after as the before and after
  texts, the after null when the guard was removed, so the two events are
  two approvals, and as the context what every marker of that name ran
  under on each side (its guard, or the first line of the `except` block it
  sits in, null when neither), each side sorted, so removing one of two
  guards of a name and removing the other are two approvals; a path gained
  by an unguarded `collect_ignore` (THREATMODEL row 81), reported in the same
  shape, has no guard on either side, so both texts are null and no path is
  bound;
- parametrized cases deleted or disabled (`param_cases_removed`): as the
  context, the rows that ran before and are no longer written (an edited
  row's old text among them) and the rows still written but newly disabled,
  each a sorted list of rows, a row being its table's argnames and cell texts
  (a JS/TS `.each`/`.for` table's included), and the live counts before and
  after, so approving one row's deletion covers no other row; a side whose
  rows cannot be read gives none, so for an unread base table only the
  counts are bound;
- a unit removed (`unit_removed`): the complete texts of its own assertions,
  in its order, a JS/TS assertion with its expected value;
- a focus added to a file (`marker_added`, file level): the focus as the
  frontend records it, its callee as written (`describe.only`, `fdescribe`)
  or its `only` option's text, as the after text; its title and arguments
  are not bound.

Texts are in the normal form above. The guard stays out of the marker
identity that alignment pairs markers on (§2b), so pairing, move detection
and the findings a diff gives are unchanged; only the key binds it (D-169,
which amends D-019). SARIF labels these keys `checkwash/v2`.

GUARDRAIL_TOUCHED, CI_WORKFLOW_TOUCHED, TEST_FILE_UNPARSEABLE, SCOPE_DRIFT,
and SNAPSHOT_CODE_COCHANGE use content-bound v2 fingerprints. Their identity
is canonical JSON containing the rule, normalized repository path, role,
change status, rename origin/destination, both source-content SHA256 digests
(null for an absent side), and the rule's structured event context. Each
source digest normalizes CRLF to LF and preserves other bytes. The complete
SHA256 of that ASCII canonical JSON is emitted as `rule/path/-/v2:<64hex>`;
no truncated identity is accepted for these rules. Revision labels, timestamps,
and local absolute paths are excluded. IR FileIR.change_evidence carries the
source digests and rename metadata; required missing or malformed evidence
is an engine error, never a legacy fallback. An optional FileIR boolean
`native_assertion_context_unchanged`, default false, separately carries the
numeric-restoration source proof: exactly one non-artifact file change, no
rename, at most one changed native bare assertion, and identical normalized
surrounding source. Inherited assertions and unknown spans cannot provide
this proof; it does not affect fingerprint identity.

The stored-expectation form of EXPECTED_VALUE_CHANGED uses the same v2
file identity and `stored_expectation_rewritten` event, keyed
`EXPECTED_VALUE_CHANGED/path/-/v2:<64hex>`; the `-` unit tells it apart
from the rule's assertion-level v2 keys above. SARIF labels both forms
`checkwash/v2`; a malformed v2 key cannot fall back to a legacy assertion key.

FileIR.normalization_equivalent_pairs is an optional sequence, default empty,
of (unit qualname, before assertion id, after assertion id) proof records.
Only a bounded non-executing projection of a closed literal call against
unchanged production may populate it. JSON arrays and typed tuple records
preserve the same comparison behavior; malformed records grant no credit.
The proof concerns the current concrete expression, not arbitrary future bugs.

FileIR.table_normalization_events is an optional sequence, default empty,
of (after unit, before text, before span, after text, after span, concrete
before subject, concrete after subject, operator, concrete expected expression).
These source-backed records add
SUBJECT_NORMALIZED findings for bounded literal-table rewrites; they cannot
remove an ordinary finding or grant equivalence/restructure credit. Records
survive JSON arrays, and malformed records raise an engine error. Source
locations are report evidence and do not enter fingerprint identity.

For these literal-table SUBJECT_NORMALIZED events, the legacy text of the
assertion-level v2 identity is canonical JSON of (unit, before text, after
text, concrete before subject, concrete after subject, operator, concrete
expected expression). JSON uses ASCII escapes and compact separators.
Operator is `Eq` or `Is`; the concrete expectation is canonical expression
text from `ast.unparse`. Before/after spans are excluded, and so are the
ordinal and count: the record alone is the identity, so it survives a JSON
round trip of the events without the units. This retains distinct concrete
row identities, including a fixed expectation declared inside an old helper
rather than at its call. Two records with the same legacy key are one
finding, as before #421.

Context includes guardrail creation/loosening, all detected CI weakening
lines, the previous parser state, effective scope globs/role, or the complete
sorted set of co-changed production identities as applicable. A different
after on the same before, or a different relevant event context, requires a
different approval. An identical reviewed content pair can survive rebasing
when its paths and relevant context are unchanged.

Legacy keys in these five namespaces, since #421 in the nine
assertion-level namespaces above, and since #512 TEST_DISABLED's, are
retired even if their expiry has not passed. They remain parsed records so
ledger deletions/rewrites remain detectable, but are excluded from
eligibility; the writer rejects new legacy keys, and `doctor` and `check`
report them. An entry's rule label cannot disguise a retired fingerprint
namespace.
Other namespaces keep their existing matching compatibility. Old reasons do
not contain enough evidence for automatic migration; re-review the intended
diff and record its complete v2 identity. Expiry and base-side loading policy
are unchanged. A ledger's own content-bound approval cannot be self-hosted
without changing its before digest; cleanup requires the maintainer's exact
reviewed governance path, not another broad exemption.

## 7. Alignment algorithm (frozen parameters)

1. Exact qualname pairing within a file.
2. Remaining units: structural fingerprint = k-shingles (k=5) over the AST
   node-kind token sequence; Jaccard similarity ≥ **0.8** pairs greedily by
   descending score; ties broken by ascending span start. If a file has more
   than **64** unpaired units, similarity pairing is skipped and the file IR
   is marked `alignment: "degraded"` (visible in findings).
3. Leftovers: before-side = removed unit; after-side = added unit.
4. Global assertion backstop: normalized texts of all removed assertions are
   multiset-matched against all added assertions across the whole diff;
   matches feed D2.

A JS/TS unit carries no structural fingerprint, so in a file that is not
degraded step 2 pairs the units left after step 1 in span order, whatever
their kind: a `.each`/`.for` table and a plain test pair as any two tests do
(#428). This records what step 2 does; it changes nothing.

## 8. Determinism rules

- No floating-point arithmetic in any verdict path.
- No network, ever, in the core path (enforced by a test that blocks sockets).
- No clock reads that affect findings, except `GREENWASH_TODAY`-overridable
  expiry (§6). Findings JSON contains no timestamps or durations.
- Source text is normalized CRLF→LF before parsing; all spans are character
  offsets into the normalized text. CPython reports `col_offset` as a **UTF-8
  byte** offset, so it is translated before use — treating it as a character
  index shifted every span on any line containing non-ASCII text, which
  garbled extracted source and defeated every text comparison built on it
  (including the self-comparison check). Determinism is promised at this
  normalized layer (identical findings JSON bytes across OSes).
- Whether a file parses depends on the analysing interpreter's grammar, which
  is the one place the running Python version can change a verdict. It is
  never silent: an unparseable test file is reported as
  `TEST_FILE_UNPARSEABLE`, high if the file parsed before this diff. The
  byte-identical claim covers source every supported version can parse.
- JSON output: sorted keys, `ensure_ascii=False`, `\n` line endings, written
  to stdout as **UTF-8 bytes** regardless of the ambient locale. (Writing
  text to a cp1252/cp950 pipe made the bytes locale-dependent and mangled
  non-ASCII evidence to `?`.) The human report may degrade unencodable
  glyphs; machine formats never may.
- Severity is a four-value enum (`info < warn < high < critical`). No scores.

## 9. Ranges, exit codes, and failure surfacing

`BASE..HEAD` is a tree-to-tree diff. `BASE...HEAD` means
`merge-base(BASE, HEAD)..HEAD` — the PR-diff idiom — and is resolved as such;
it must never be silently downgraded to two dots, which would pull
base-branch prod commits into the diff and disarm E1.

`0` = no finding at or above `fail_on` (default `high`);
`1` = verdict block;
`2` = engine error — including any unexpected exception. An unhandled
traceback exiting 1 would be indistinguishable from a real block for CI, so
every crash path is mapped to 2.

`check --format hook-json` (the Claude Code Stop hook) exits 0 on both verdicts: on a block its JSON carries `"decision": "block"` and a `reason`; on a pass it carries no `decision`, and is `{}` unless a session note below applies; a stop released under `stop_hook_active` (below, D-189) carries no `decision` either, only a `systemMessage`. An engine error, or a config or allowlist parse error under `on_engine_error = "block"`, exits 0 there too, with a JSON `systemMessage` saying the change was not analysed and why, and no `decision`. The hook is an author-side check; the required CI check remains the gate (#414). With `--emit-ir`, every engine error keeps exit 2. One engine error blocks instead: a size refusal (§4b) of a change in the diff that decides the verdict (HEAD against the working tree for the Stop hook, or the range given) exits 0 with `decision: block` when any unread side of that change is its head or worktree side, and the `reason` names that side's path, side, size and limit and says to shrink or split the file, or revert the change to it (#456). It blocks on every stop, `stop_hook_active` or not, since it is not the path a stop is released on (D-189, below). Any other size refusal keeps that `systemMessage`: of a change whose base side alone is over the limit; of a base manifest, config, exemption list or `--task` file; of a file the diff does not hold; and, with a range, of a pytest configuration's symlink target that no detector must read (§4b), which is read through the link even when the diff changes the target. The run refuses only the first must-read change it meets, so a padded file the diff lists after a change whose base side alone is over the limit keeps it too. One in the session-commits analysis below keeps that analysis's note.

**The block reason (D-189).** Since 0.11 a block on findings gives this `reason` from `check --format hook-json`, whichever Stop handler runs it, with `--hook-input stdin` or without: `checkwash: N finding(s) blocking. RULE path :: unit — message. Fix the production code if it is wrong. Do not weaken, skip or remove the test, and do not add an exemption or change checkwash's configuration or hooks yourself: if you believe the test change is correct, tell the user which finding blocks and why, and let the user decide.` It names the first of the findings at or above `fail_on` that no exemption covers. It offers no `checkwash allow` command, no fingerprint and no other way round, since the exemption is the user's decision; this replaces D-142 item 6, under which the reason carried the `checkwash allow` command for the first finding and, with a session base other than HEAD, the next-session sentence below. The size refusal's block (#456) keeps its own reason. The reason text therefore differs from 0.10's for every Stop handler, flag or not; where this section says a run is "the one without the flag", it compares two runs of the same version.

**The managed Stop hook's window (#418).** `hook session-start`, the managed SessionStart handler, reads the hook input from stdin and records HEAD as `{"created": <UTC time>, "head": <commit>, "version": 1}` in `<git-dir>/checkwash/sessions/<sha256(session_id)>`. It writes only when no record exists, and never when `source` is `compact` or `resume`. After writing, it prunes other sessions' records that are older than 30 days or name a commit that is gone, never by count; it never prunes the starting session's own record, or one that does not parse. A record is read only as a regular file of at most 4,096 bytes. It prints nothing and exits 0 on every outcome.

`check --format hook-json --hook-input stdin`, the managed Stop handler, reads the hook input from stdin: at most 1,000,000 bytes, never from a TTY, waiting at most 10 seconds. The flag with another format or with a range is a usage error, exit 2. Without the flag, or with no input (empty stdin, a TTY, nothing within the wait), the run is the one without the flag, byte for byte. With input, the *session base* is the recorded commit when HEAD descends from it, and otherwise their merge base:

- **A session base other than HEAD:** HEAD against the working tree decides the verdict, as before, with configuration, exemptions, the `--task` contract and manifests read from the session base. Until 0.11 a block on findings added to its `reason` that an exemption, config change or hook upgrade committed during the session applies from the next session, and that `/clear` starts one. Since D-189 that sentence is for the user, not Claude: a block's `reason` no longer carries it, and a stop released under `stop_hook_active` (below) adds it to its `systemMessage`. A size refusal's block never carried it, since its remedy is to shrink, split or revert the file, not a policy change. On a pass, the session base against the working tree is analysed too, and its findings at or above `fail_on` are named in a non-blocking `systemMessage`, which says the required check will judge them; a block leaves them to a later Stop. An engine error in that second analysis is a `systemMessage` saying the session's commits were not analysed; the verdict stands.
- **A session base equal to HEAD:** the output is the one without the flag, except that a stop can be released under `stop_hook_active` (below).
- **No usable record** (input that does not parse, no `session_id`, no record, a record whose commit Git cannot compare with HEAD, or HEAD with no history in common with it): the run is the one without the flag, and a pass adds a `systemMessage` saying the session's commits were not analysed and why. Input that parses and carries a `session_id` can still release a stop under `stop_hook_active` (below), since the Stop record does not depend on the session record.

**A stop that is not blocked again (D-189).** With `--hook-input stdin`, a block verdict on findings, the input's `stop_hook_active` exactly JSON `true`, and a blocking set identical to the one this hook last blocked on in the same session, the output carries no `decision` and a `systemMessage` for the user: `` checkwash: this stop was not blocked again, but N finding(s) still block this change: <findings>. Claude was told once to fix the production code or report it to you. Review the change before relying on it; `checkwash check` lists each finding and how to record a reviewed exemption. `` The findings are named as the session note names them: at most five, most severe first, then `; and N more`. With a session base other than HEAD it adds `An exemption, config change or hook upgrade committed during this session applies from the next session; /clear starts one.` Every other case blocks: no block recorded for the session (a continuation another Stop hook caused), a different set, a `stop_hook_active` other than `true`, no `session_id`, input that does not parse, no input, or no `--hook-input`. The blocking set is the sha256 of the sorted fingerprints of the findings at or above `fail_on` that no exemption covers, one per line. Each block on findings whose input carries a `session_id` records it as `{"blocking": <digest>, "version": 1}` in `<git-dir>/checkwash/sessions/<sha256(session_id)>.stop`, written to a temporary file and renamed into place, and read only as a regular file of at most 4,096 bytes without following links; a pass deletes it, and an engine error leaves it. When `hook session-start` prunes (above), it also removes other sessions' `.stop` records older than 30 days by modification time, never the starting session's own. The agent can write these records too (THREATMODEL item 2). The size refusal's block (#456) is a separate path and blocks on every stop. A released stop gives no session-commits note; that note is for a pass. Blocking the same set again told Claude nothing new and only pressed it to change the test. A pre-registered Claude Code lifecycle receipt (D-189; Claude Code 2.1.260, `-p` mode, haiku, Windows) observed a first stop blocked with the reason above and the continued stop answered with no `decision` and this `systemMessage`, which came back in the hook event output and as Claude Code's own `informational` notice event ("Stop says: checkwash: this stop was not blocked again, ..."), so the managed handler received `stop_hook_active: true` on the continuation. Whether the interactive UI displays the `systemMessage` to the user is not verified.

**The managed PreToolUse hook (0.11, D-189).** `hook pre-tool-use`, the managed PreToolUse handler, asks the user before an Edit or Write weakens a Python test. `main()` dispatches it before argparse: it takes `--repo` (default `.`) and ignores every other argument, prints exactly one JSON object, ASCII-escaped with sorted keys, and exits 0 on every outcome, since a PreToolUse hook that exits 2 blocks the tool call. `{}` leaves the call to Claude Code's normal permission flow. An ask is `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": <reason>}}`. The rule set and threshold below come from D-189 and the session replay behind it, which covered Python test files only.

- **Input.** The hook input is read from stdin as the Stop handler reads it, but up to 8,000,000 bytes, since a Write carries the whole file, with the same 10-second wait. Anything but a JSON object with `hook_event_name` `PreToolUse`, `tool_name` `Edit`, `Write` or `MultiEdit`, and an object `tool_input` whose `file_path` is a string ending `.py` is `{}`; on Windows the ending is read as the file system writes it, with a last part's trailing dots and spaces dropped and case folded, so `test_x.py.` and `test_x.PY` count. That much is checked before any Git call. The run then re-roots as `check` does (#416), and a directory Git does not place in a repository is `{}`.
- **Path.** A relative `file_path` is joined to the input's `cwd`, which must be absolute. The path is resolved through links and junctions, as the write resolves it, and must lie inside the work tree's resolved root; on Windows each part's trailing dots and spaces are dropped, as Windows creates the file. It is `{}` for a path outside the work tree, a part `.git` or a part containing `:`, a path inside a nested repository or submodule (a directory on the way holding `.git`), a NUL, CR or LF in the path, or a path that is not UTF-8.
- **Policy.** `config.toml` and `allow.toml` are read from the session base when a usable session record exists, as for the Stop hook (#418), and otherwise from HEAD (§1, §6). No `--task` is read (§4c). Only a judged Python test is asked about: a path that, as resolved, ends `.py` and whose role under that configuration is `test` or `conftest`, or that pytest's default collection runs (`collectable`, #219). JS/TS tests are not asked about in 0.11. Anything else is `{}`.
- **The change.** The before side is the path's current working-tree bytes; an absent file makes the change an addition, and a working-tree read the snapshot refuses (a directory, a link, a path leaving the repository) is `{}`. The after side is predicted from the tool input. A Write's is its `content`. An Edit's is the working-tree text, decoded as strict UTF-8, with `old_string` replaced by `new_string` exactly once, or at every occurrence with `replace_all`. For an Edit, no occurrence, several without `replace_all`, `old_string` equal to `new_string`, a field of the wrong type, or a working-tree file that is not UTF-8 is `{}`: the tool call fails, or its result is not predicted. An empty `old_string` is accepted only for an absent or empty file, which then holds `new_string`. When the file holds CRLF line ends and no bare LF, both strings' line ends are converted to CRLF first. A MultiEdit, whose input Claude Code does not document, applies its `edits` in order under the same rules. A lone surrogate in the text is `{}`, and so is an after side equal to the before side.
- **Size.** Either side over the 1,000,000-byte source limit is asked about, naming path, side, size and limit (§4b); the working-tree side is checked before the edit is predicted.
- **An unparseable working copy.** When the before bytes do not parse as Python and HEAD's copy does, HEAD's copy is the before side, so a weakening finished in this edit still has before units to compare. An edit that makes a parseable test unparseable is asked about: each unit that vanishes is a `TEST_DISABLED` finding.
- **Analysis.** The diff is that one change. Every other path is read from the working tree, and the path itself from the proposed bytes, so the conftest chain, importer search and collection inventory see the new content; pytest configurations pair the working tree against that proposed tree. E2 is forced on (§4c); the gating table is unchanged.
- **The ask.** The hook asks when any finding under `ASSERT_WEAKENED`, `ASSERT_REMOVED`, `TEST_DISABLED`, `TOLERANCE_LOOSENED` or `BROAD_EXCEPT_ADDED` that no exemption covers is at `high` or above, on any path, since a helper's change can surface on its importers. The threshold is fixed at `high` and does not follow `fail_on`. Every other rule, the expected-value family among them, is left to the Stop hook and the required check. The reason is `checkwash: this edit weakens a test (N finding(s)): RULE path :: unit — message; ...`, with at most three findings and then `; and N more`, followed by `Approve only if the weaker test is intended. If you deny it, Claude should report the finding to you, not make the same change another way.` Unprintable and bidi control characters in the findings are escaped as `\uXXXX`, and this reason is at most 1,200 characters. It names no `checkwash allow` command and no fingerprint. A size ask reads `checkwash: this edit was not analysed: <path (side, size > limit bytes)> is over the source byte limit, so a weakened test in it would not be seen.` with the same closing sentences.
- **Not analysed.** An engine error once the path is judged a test, other than the working-tree read refusal above, a base `allow.toml` that fails to parse under `on_engine_error = "block"` (a `config.toml` that fails to parse falls back to the defaults, which are `pass_with_warning`), or no answer within 30 seconds leaves the edit not analysed. Under the base policy's `on_engine_error = "block"` the hook asks with `checkwash: this edit to PATH was not analysed before it was made, so it was neither asked about nor passed. Engine error: <detail>`; otherwise it prints `{"systemMessage": <the same text>}` and no decision. Unlike the Stop hook, where no engine error but the size refusal above blocks (#414, #456), `block` here asks. An error or the deadline before the path is judged a test is `{}`. At the 30-second deadline the process prints its answer and exits 0 at once, without waiting for the analysis.
- **Claude Code.** Claude Code's hooks documentation (code.claude.com/docs/en/hooks, read 2026-10-28) says the ask reason is shown to the user in the permission prompt; in a `-p` run nobody can answer, so the call is denied and Claude reads the reason; `ask` also prompts in auto mode; exit 0 with no output leaves the normal permission flow; and a hook that times out does not block (default timeout 600 seconds). A pre-registered Claude Code lifecycle receipt (D-189; Claude Code 2.1.260, haiku, Windows) ran in `-p` mode only: under `acceptEdits` and under bypassPermissions alike, an Edit with an `ASSERT_WEAKENED` finding was asked about, and Claude Code denied it with the reason in the tool result and left the file unchanged, so bypassPermissions did not skip the ask in `-p`. Not verified: the permission prompt in an interactive session, in any mode, bypassPermissions included; auto mode; a timed-out hook; a Write call, the other four rules, the size ask and the engine-error ask; whether a `systemMessage` in PreToolUse output reaches the user; the shape of a MultiEdit input; and other Claude Code versions, models and platforms.
- **Installation.** `hook install --agent claude-code` writes machine-local `.claude/settings.local.json` by default since 0.11, and only that install adds this handler, in a group `{"matcher": "Edit|Write|MultiEdit", "hooks": [<handler>]}` on the Stop handler's runtime binding. The handler runs a bootstrap of its own that exits 0 whatever the bound runtime does, so an older checkwash at the bound path, which would answer with a usage error, exit 2, and block every edit, prints nothing on stdout and exits 0 instead; the install probes it with `{}` on stdin and requires exit 0 and `{}`. `--shared` writes `.claude/settings.json` with no PreToolUse handler, since a teammate whose PATH holds a checkwash older than 0.11 would answer every Edit and Write with exit 2.

The hook is an author-side check, like the Stop hook. An edit made through Bash or any tool the matcher does not name never reaches it, an approved ask lets the edit through, and the required CI check in range mode remains the gate.

The block reason, the released stop and this hook come from D-189. On 2026-10-28 Nelson clicked the button labelled 「加 PreToolUse ask」; the button's label and its option text were written by Claude, the option text was "0.11 加 PreToolUse ask，只問五條弱化規則；先修擋下訊息和 stop_hook_active，Stop hook 凍結預設另外再議", and only the label may have been sent. The detailed choices in this section are Claude's under Nelson's 2026-10-27 delegation (「Checkwash 一樣給你」; docs/RELEASING.md). The Stop hook applying `oracle_freeze` by default is deferred.

Base-side `config.toml` / `allow.toml` that fail to parse are never silently
ignored: the diagnostic goes to stderr and to `config_errors` in the JSON
payload, and with `on_engine_error = "block"` the run exits 2 (in
`check --format hook-json`, 0 with the `systemMessage` above).
`hook pre-tool-use` writes no such diagnostic: under `block` it asks as for an
edit not analysed, and otherwise it goes on as the other modes do, leaving the
diagnostic to the Stop hook and the required check (D-189). A hardened
gate must not quietly revert to defaults, and a corrupt ledger must not
quietly void every exemption in the repo.

A changed side set aside unread (§4b) is not dropped silently either: its
stderr note names path, side, size and limit, and so do an entry of the
optional `unread` key in the JSON payload (omitted when empty), a SARIF tool
execution notification and a `!` line of the term report, whose head then
reads "analysis incomplete" when there is no finding, allowlisted or not;
`check --format hook-json` and `--emit-ir` do not name it (#454).

A size refusal (§4b) names its side on stdout too, though the run still
exits 2: under `--format json`, without `--emit-ir`, stdout is
`{"unread": [<entry>]}`, one such entry for the side the refusal and its
stderr line name, which is the base side when both sides of a change are
over the limit, except where #455 names the side that holds the shebang.
It is not a findings document: it carries no
`checkwash_findings_version`, `findings` or `verdict`. Term,
sarif and `--emit-ir` keep an empty stdout. So do a root manifest, config,
exemption list or `--task` file over the limit at the base, which is
refused before the analysis; with a range, a pytest configuration's
symlink target over the limit that no detector must read, which is
refused as it is read through the link (above); and every other engine
error (#454).

**Which directory a command reads (#416).** `check`, `sweep`, `allow`, `doctor` and the `quality` forms that read a repository (a range, the worktree review, `init`, `doctor`) first ask Git about `--repo` (default `.`) with `git -C <--repo> rev-parse --is-inside-work-tree --show-prefix`. If Git answers `true` with a non-empty prefix, a second query, `git -C <--repo> rev-parse --show-toplevel`, names the root. Its answer must decode as UTF-8, be a single line, be absolute and name an existing directory. The command then uses that root in place of `--repo` for every later Git call and working-tree read. A run from a subdirectory therefore analyses the whole repository. For `check`, `sweep`, `doctor` and the `quality` forms its stdout and exit code are those of the same run at the root; `allow` writes the root ledger and names it under Git's spelling of the root. This is not the behaviour of `git -C <subdirectory>`, under which `ls-tree` and `git grep` stay scoped to the subdirectory. The root is never `--repo` joined with `--show-cdup`.

A re-rooted run prints one line on stderr: `checkwash: using the repository root <root>, not its subdirectory <prefix>`. The line may name `.checkwash/` or `.greenwash/` directories in the working tree. It checks the invoked directory and each directory between it and the root, but not the root itself. If any exist, the line continues `; not read: <paths> (only the root's .checkwash/ or .greenwash/ applies)`. The line is written in every format, including `json`, `sarif` and `hook-json`, and changes neither stdout nor the exit code.

Git may answer `false`, or `true` with an empty prefix: at the root, in a bare repository, or inside `.git`. In those cases `--repo` is used unchanged and nothing is printed. `hook install` never asks Git; it writes under `--repo` as given. `quality profiles`, `quality explain`, `bench` and `demo` never look up the root either; their `--repo` is not re-rooted.

`checkwash doctor` asks in the same sanitized Git environment its own later queries use, without their discovery ceiling. In that environment the caller's `GIT_*` variables are removed, and global and system configuration, prompts and optional locks are off. So a caller's `GIT_DIR` or `GIT_WORK_TREE` cannot point it at another repository. The other commands ask in the caller's environment, as their later Git calls do.

When Git cannot answer, `check` and `sweep` report an engine error: exit 2, or exit 0 with the non-blocking `systemMessage` for `check --format hook-json` (#414). `allow`, `doctor` and the `quality` forms instead use `--repo` as given, as before #416:

- The fallback is silent when the first query fails or its answer is not a `true`/`false` work-tree answer: outside Git, with a missing directory, or with no git binary.
- One stderr line is printed when Git has answered that `--repo` is a subdirectory and then the root cannot be resolved. That covers a first answer of `true` whose prefix is unusable (undecodable, containing `..`, or split by a newline in a directory name), an unusable root, and a second query that fails or times out. The line is `checkwash: could not resolve the repository root: <reason>; using --repo as given`. stdout and the exit code are those of `--repo` as given, and `quality` keeps its own JSON error reporting.

`check` validates the syntax of a range before the lookup, so a malformed range is still `error: range must be BASE..HEAD` (or `BASE...HEAD`) with exit 2 in every format, `hook-json` included, whether or not Git can answer.

Where the first query exits non-zero (outside Git, or a missing directory), the engine-error text of `check` and `sweep` now names the lookup's query (`git rev-parse --is-inside-work-tree failed: ...`), not the first Git call that failed before. With no git binary, or when the query times out, the text is `git read could not complete`, as before. Where the lookup succeeds, range validation and its exit 2 are unchanged.

## 10. Corpora: tuning versus held-out

Every false-positive rate this project publishes is a measurement on a set
of real commits, and it is only as honest as the answer to one question:
**had the people shaping the detectors read those diffs before the number
was taken?** This section names the two answers and fixes what each may be
called. It exists because the README said "none seen during development" of
a corpus that had been re-run after every precision round since 2026-07-30
(corrected 2026-09-02, PR #66), and because nothing in this file,
THREATMODEL or DECISIONS had defined the distinction.

### 10.1 Definitions

- **Tuning corpus (in-sample).** A repository is in-sample once any of the
  following has happened: a window of its history was swept during a
  precision round; a blocked diff from it was read by anyone shaping a rule,
  credit, fixture or threshold; a finding from it was triaged into an issue,
  a THREATMODEL row or a DECISIONS entry. In-sample is a property of the
  *repository* and it is permanent: a fresh window from the same repository
  is still in-sample, because the detectors were shaped on its conventions.
  Today: wave 0 (`attrs`, `click`, `flask`, `httpx`, `rich`, `starlette`;
  in-sample since 2026-07-30), the three 2026-08-07 integrations
  (`requests`, `jinja`, `pydantic`; `docs/integrations.md`), and every
  repository of the 2026-09-01 field run (`benchmarks/external/2026-09-01/`,
  spent by the rounds that closed issues #53 and #55). Of wave 1, the
  repositories that also appear in that field run (`aiohttp`, `pandas`,
  `sqlalchemy`) are spent; the rest are unspent until the corpus catalogue
  records otherwise.
- **Held-out corpus.** A repository that no engine version has swept during
  development and none of whose diffs anyone shaping the detectors has read.
- **Spending.** A held-out set is spent the moment its blocks are
  adjudicated or its findings read. Sweeping it and publishing the raw block
  rate does not spend it; opening the diffs does. Spent sets do not come
  back.

### 10.2 Rules

1. **Label it or it is not a claim.** Every published rate names its class
   — `in-sample` or `held-out` — and the engine version it was measured on;
   a held-out rate also names its draw date. README, the authoritative table
   in STATE and `benchmarks/RESULTS.md` carry the label next to the number.
   A rate without the label is a typo to fix, not a result to cite.
2. **Draw before you look.** A held-out set is drawn and recorded *before*
   any engine runs on it: repository, remote, pinned commit, window (the
   newest N non-merge commits at draw time), the engine version to be
   measured, and the pre-registered expectation (rule 5). The record is
   committed to `checkwash-corpus` (`records/holdout/<date>/`) before the
   sweep. Nothing in the catalogue's wave 0, nothing spent from wave 1,
   nothing in `records/field-runs/` and nothing from a prior draw is
   eligible.
3. **One measurement, then it is tuning corpus.** Sweep, publish the raw
   block rate with its label, *then* adjudicate. Adjudication spends the set:
   the catalogue records the spend date, and every later number on those
   repositories is in-sample. The adjudicated false-positive rate is
   published as "held-out, adjudicated (now spent)".
4. **A held-out number belongs to its engine version.** When detector logic
   changes after the last held-out measurement — a rule, a credit, a lattice
   value or an alignment parameter; not a pin, a rename or a docs change —
   that number is stale: it stays published with its version, and no
   release may present it as the current out-of-sample rate. A release that
   wants to state one draws afresh (rule 2). Trust-lag and rename releases
   such as v0.2.10 and v0.2.11 do not stale it.
5. **Prediction first.** The draw record states, before the sweep, the
   expected direction against the in-sample rate. Both held-out measurements
   so far came out worse than in-sample — by half a point (2026-08-07) and by
   more (2026-09-01) — and that is the prior. A held-out result *better* than
   in-sample is an anomaly to explain (window, repository shape, opaque
   share), never good news to headline.
6. **The check must be able to fail.** The labels are pinned by tests the
   way `tests/test_state_claims.py` pins the authoritative table, and the
   catalogue is the single record of what is spent. A number that cannot be
   traced to a labelled, dated record is removed, not defended.

### 10.3 Transition (2026-09-02)

No held-out number exists for the current engine. The 2026-08-07 figure
(three repositories, 667 commits) and the 2026-09-01 figure (thirteen
repositories, 2,300 commits, engine v0.1.49) are both stale under rule 4 and
both spent under 10.1; they remain published with their dates and versions
as history. The README "Honest cost" row still states its out-of-sample
figure without an engine version, and STATE's authoritative table carries
no class label: rule 1 applies to them from the next number published, and
the label tests of rule 6 land with the first draw under rule 2. Until that
draw, the only rate this project may call current is the in-sample 46/1800
(engine v0.3.0, swept 2026-09-07), labelled as in-sample.

### 10.4 What this does not promise

Held-out measures precision on commits nobody tuned on. It does not measure
recall against an adversary — the tamper, disguised-refactor and decoy arms
under `benchmarks/` do that, and they are in-sample by construction. It does
not make the in-sample rate wrong: 46/1800 (v0.3.0, 2026-09-07) is the honest answer to "how often
does it block the repositories it knows best", and it stays published as
exactly that.

### 10.5 Published identity of the release-regression baseline (D-186)

The previous-release verdict corpus compares against actual published software,
not an undelivered tag. On a tag-stage run, the baseline remains the highest
other published stable GitHub Release whose native tag is merged into the exact
pushed commit. Complete bounded public Release catalog evidence, native tag
object/peel and ancestry, and the baseline's uploaded canonical pyz identity
must agree with its existing source/byte pin. A higher merged published Release
with missing or bad assets blocks; it is never silently excluded. Bare tags
remain recorded, including failed unpublished tags. Catalog absence describes
current public metadata, not never-published history or private drafts.

The gate captures two complete consistent catalog traversals and original
response bytes/status/Link/times/hashes. The native publisher independently
refreshes and re-evaluates relevant published fields and native tag identities.
Failed, capped, partial, drifting or unbound metadata is not absence or PASS.
The pushed tag still points exactly to HEAD and is excluded from previous-release
selection. No tag, baseline pin, case, label, acceptance entry, baseline-blocked
set, T3 map or canary pair changes merely to obtain a passing tag check. Ordinary
case engines remain zero-network; this is a separate tag metadata preflight.
