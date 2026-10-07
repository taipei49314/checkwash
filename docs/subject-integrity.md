# Subject installation and runtime provider boundaries

This is the source contract detail for the T-326 candidate built on v0.3.3.
It does not certify a release, a completed family qualification, or a fresh
false-positive measurement. Existing policy severities, alignment parameters,
strength values and fixture labels are unchanged.

## Installation effects

An installation contributes an event only when all three facts are proved:

1. The same collected test unit has a live oracle on both sides.
2. A statically bound first-party target is replaced, and that replacement
   reaches the oracle on the head side.
3. The same target/kind/replacement effect did not already reach that test's
   oracle at base. Moving or reformatting an unchanged installation is not a
   new effect.

The additional source pass handles attribute assignment, rebinding an imported
local name, native `setattr` (including an imported builtins alias), literal
`vars(module)[name]` and `module.__dict__[name]` assignment, native
`monkeypatch.setitem(vars(module), name, value)`, and literal
`sys.modules[module_name]` replacement. A literal
`importlib.import_module(module_name)` supplies module identity. Arbitrary
objects or local functions named `setattr` are not installation APIs.

Existing monkeypatch/mock patch API handling remains in the ordinary frontend;
its earlier activation fixes and its published IR fields are retained. The new
pass adds evidence and does not replace main with the old stand-in checkpoint.

Supported source scopes are module setup; bounded called same-file helpers;
existing test functions; applicable root/ancestor conftests; requested or
literal-autouse fixtures; and the named pytest setup hooks
`pytest_configure`, `pytest_sessionstart`, `pytest_collection_modifyitems`,
`pytest_collection_finish`, `pytest_generate_tests`, and `pytest_runtest_setup`.
Fixture public-name aliases and direct-parametrize shadowing are read from
literal syntax. Class fixtures are restricted to their owning test class.

Timing is part of the evidence. Setup module/early-hook effects precede test
imports. Fixtures and later hooks follow test-module imports. A module object
lookup can see an attribute changed by a fixture, while an already-captured
`from module import function` binding does not change retroactively. The
builtin fixture `request.module` can replace the test module's own imported
binding. Fixture execution stops at its first yield: teardown cannot install
a stand-in under an earlier assertion. Restoring a captured original before
the lookup removes the effect; a result already computed by the stand-in
retains its provenance after restoration.

Test-local events use `TEST_PATCHES_SUBJECT`; conftest events use the existing
`CONFTEST_PATCHES_PROD` channel. Base severity and escalation remain in the
existing policy. Snapshot source files establish ownership at either the
repository root or conventional `src/`; stdlib and declared external roots
remain hygiene exclusions.

This is a bounded source proof. Unknown branch selection, dynamic names,
external plugin fixtures, recursive/helper closure execution, class inheritance
and fixture override-super chains, and arbitrary runtime import machinery are
not claimed as complete. It is not proof that every replacement spelling in
every Python execution model is detected. Changed fixture registration alone
can affect existing test consumers. Discovering those consumers uses the full
path inventory, or the existing strict empty-needle search over nonempty Python
sources: empty modules cannot contain oracles. An ordinary stdlib setup edit or
a formatting-only edit of an existing installation does not open that scan.

Legacy direct callers without a strict source reader retain their established
detector coverage; this additional installation pass does not infer repository
ownership from an omitted callback. A reader without either consumer inventory
callback can analyze changed test consumers only. CLI and candidate mapping
adapters supply the complete callback set. Source parsing is limited to 1 MB
and 30,000 syntax nodes per file, 64 MB of changed or discovered context, 4,096
memoized source reads and one million total symbolic execution steps (also
20,000 per individual trace). Ownership probes share the bounded reader.

## JavaScript module mocks and replacing spies

Issue #177 is the JavaScript spelling of the same installation:
`vi.mock("./src/billing.js", () => ({ invoiceTotal: () => 78.75 }))` added
above an untouched `expect(invoiceTotal(items)).toBe(78.75)`. The JS pass
(`src/checkwash/frontends/javascript/module_mocks.py`) emits the same
`TEST_PATCHES_SUBJECT` event when three facts hold:

1. The JS test unit exists on both sides, carries no liveness marker on
   either side (a skip or todo, a conditional disable, an inverted oracle
   such as `.fails`, or a focus elsewhere in the file), and has represented
   assertions after the change.
2. A stand-in for a first-party module, or for one member of it, reaches one
   of those assertions on the head side — directly, or through one hop of a
   local binding that is not rebound. A namespace or `require()` module
   object reaches it only through a member (`billing.invoiceTotal`): read
   whole, as in `compute(billing)`, it names no export. A named or default
   import names its export in any use (#196 188.3, as Python's row 90).
3. The base side of the same file had not already installed that target for
   this unit: at module level, in a hook, a `describe` body, a helper, or the
   unit itself. An installation inside another test never ran for this one,
   so copying it into this test is a new stand-in (#196 188.2, as Python's
   per-unit condition); a `vi.mock` runs for the whole file wherever it is
   written. Moving an installation between those places, reformatting it or
   switching runner spelling is not a new stand-in.

First-party means a `./` or `../` specifier that stays inside the repository
and outside dependency or build output; `./billing`, `./billing.js` and
`./billing.ts` name one module. Two kinds of alias name first-party modules
too (#196 188.6):

- an `@/` or `~/` specifier, by convention the project's own source root:
  the same alias string in a mock and an import is one module, so
  `vi.mock("@/billing")` stands in for `import ... from "@/billing.ts"`;
- a specifier the base side's root `tsconfig.json` maps through
  `compilerOptions.paths`, relative to `baseUrl` or the repository root: it
  names the module at the path it maps to, so under `"@/*": ["src/*"]`
  `vi.mock("@/billing")` stands in for `import ... from "../src/billing"`.
  An exact pattern comes first, then the longest prefix, and the first
  target is the module, as TypeScript resolves it. The base side's file is
  read, so a diff cannot remap its own mocks.

Without the tsconfig, an alias and another spelling may still name one
module; a base-side installation under such a spelling counts as already
installed, so respelling a mock is not a new stand-in. Bare specifiers
(packages, `node:` builtins, scoped packages such as `@acme/billing`) are
hygiene. Other aliases (`#imports`, root-relative `/src`, a bare specifier
`baseUrl` alone resolves, a `"*"` pattern, `extends`, `jsconfig.json`,
bundler and runner alias configuration) resolve through configuration the
scan does not read, so they stay silent rather than guessed.

Timing is modelled, not executed. `vi.mock` is hoisted above the file's
imports wherever it is written and reaches every binding of the module in
every test: Vitest 3.2.7 and 4.1.11 apply one written in a test, a `describe`
body, a hook or a helper that never runs to the whole file (4.1 warns), and
Vitest 5.0.3 refuses such a file (#196 188.1). `jest.mock` is hoisted only
within its own block: at module level it reaches every binding, and written
in a test, a `describe` body or a hook it reaches only `require()`/`await
import()` bindings evaluated after it (Jest 30.5.2 keeps the real module for
a top-level `require`). `vi.doMock`, `jest.doMock`, `jest.unstable_mockModule`,
`jest.setMock`, node:test `mock.module` and `t.mock.module` reach only
`require()`/`await import()` bindings evaluated after them, never a static
import. Member replacements —
`vi.spyOn`, `jest.spyOn`, `vi.mocked(x)` or `jest.mocked(x)` chained to a
replacing `mock*` call, `x.mock*(...)` on an imported binding (also through a
TypeScript cast or non-null assertion: `(x as Mock)`, `(<Mock>x)`, `x!`),
`jest.replaceProperty`, and node:test `mock.method` with an implementation —
reach reads after them in the same test, or every test when written at module
level. A spy created in one statement and replaced in another
(`const spy = vi.spyOn(...)` then `spy.mockReturnValue(...)`, the same for
`jest.spyOn`, `vi.mocked` and `jest.mocked`, and node:test's `mock.method`
without an implementation, replaced through `fn.mock.mockImplementation(...)`)
is read through one hop of the local binding on either side, and takes effect
where the replacing call runs (#196 188.4). A factory that reaches for the original module (`importOriginal`,
`importActual`, `requireActual` or its own parameter) replaces every name it
spells — an identifier, a member name, or an identifier-shaped string literal
such as a quoted or computed key — and nothing else; no factory is an
automock. Vitest's `{ spy: true }` and a spy without a replacement keep the
real code and install nothing. An object-literal key inside an assertion
(`toEqual({ invoiceTotal: 78.75 })`) names a property; it does not read the
binding of the same name.

A setup file the runner loads before every test file is read as a conftest
is (#218): `setupTests.js` or `setupTests.ts` (Create React App's
`src/setupTests`), `jest.setup.*`, `vitest.setup.*`, and the files the base
side's root `package.json` names in `jest.setupFiles` or
`jest.setupFilesAfterEnv` as `./x` or `<rootDir>/x`. A first-party module mock
or replacing spy installed there, read by the same scan, a
`jest.enableAutomock()` there, and `"automock": true` under the root
`package.json`'s `jest` key are reported as `TEST_PATCHES_SUBJECT` with no
unit when the base side did not install them: which test reads the stand-in
is not resolved, as `CONFTEST_PATCHES_PROD` does not resolve it, so no unit's
repair evidence explains it. A mock moved between setup files or reformatted
is not new; a third-party mock is hygiene.

Not claimed: a rewritten manual mock under `__mocks__/`; runner config files
(`jest.config.*`, `vitest.config.*`) and what they set, their `setupFiles`
and `automock` among them; a setup file that only the head side's
`package.json` names, under another name; `globalSetup`;
installations other than `vi.mock` in hooks, helpers and `describe` bodies;
a namespace or `require()` object passed whole under a whole-module mock
(`compute(billing)`); plain assignment to a module object's member; template-literal keys and partial-factory names
spelled outside the factory (a spread of an object declared elsewhere, a
computed key from a variable); cast types that contain parentheses;
non-literal specifiers; re-exports and two hops; and oracles the JS frontend
does not represent (interaction matchers, `.resolves`/`.rejects`,
snapshots). Severity and escalation are the existing policy: a modified JS
production file is opaque, grants repair evidence and holds the event at
warn.

## Runtime provider shadowing

The runtime provider predicate requires an active imported module in an
existing collected test or its active fixture graph on both sides. A bounded
search plan selects first-party provider bytes at base and different provider
bytes at head. Plans cover regular/namespace packages, bounded
`pkgutil.extend_path`, pytest prepend/append behavior, literal pytest
pythonpath/import-mode configuration, supported conftest `sys.path` edits,
and concrete recognized runner environment/command spellings. A path suffix
collision alone is not a finding.

Provider identity includes the selected module and every executed package
initializer in its chain. AST identity uses the cross-version stable dump;
Python bytes parsing honors encoding cookies. Large/unparseable providers use
exact byte hashes instead of being treated as equivalent.

The two-commit form is also bounded: an already-winning provider is reportable
when it matched another first-party provider at base and the changed executable
chain now differs from that alternate. A deliberately divergent duplicate is
not automatically a shadow. Changing both copies together so that they remain
equivalent does not create a shadow finding.

Relative imports use a package anchor proved from the corresponding side's
regular-package initializer inventory, including empty `__init__.py` files.
Imports above that package root, unused imports and standalone files without
a proved package anchor do not establish subjects. Cache keys include the
package context; identical bytes in different packages cannot share an import
resolution answer. Search hints include individual module components so a
relative import is not lost by searching only for the absolute dotted name.
Namespace/importlib cases without a proved regular-package anchor and dynamic
import hooks remain outside this relative-import extension.

The event uses `TEST_PATCHES_SUBJECT` with `unit=None`, retaining the audited
policy and avoiding provider self-credit. Executable-equivalent switches are
silent as shadow findings but their replacement paths and controls still do
not contribute production repair symbols, callers or literals. Copying the
same implementation is not a repair for an unrelated weakened assertion.

## Snapshot and adapter contract

`analyze`/`build_ir` accept additive `root_path_lister` and `root_batch_reader`
callbacks, alongside the existing strict `root_reader`/`root_searcher`.
The list/batch pair must describe one complete selected revision/working-tree
source view. CLI range analysis and sweeps use `GitSnapshot`; worktree analysis
uses `WorkingTreeSnapshot`; demo/mapping callers pass the complete mapping.
Callers that supply no inventory do not acquire a complete runtime-provider
analysis by implication.

Full inventory includes empty modules and non-Python config/runner files.
The existing empty-needle search still means nonempty Python source and is
not reused as the runtime-provider inventory. Its use by the installation pass
is restricted to discovering oracle consumers. Git path metadata is read once per snapshot;
selected regular blobs are read in batches of 256 by immutable object IDs.
Missing required blobs, malformed paths/records, unsupported selected source
or incomplete batches fail with `EngineError`. A submodule is listed as its
path with a trailing slash, a directory whose content is unknown (#335). A
read inside one, an import that resolves into one, or a pytest collection that
can reach one on either side of the diff fails with an `EngineError` naming
its path; every other pass proceeds over the rest of the tree. A run reaches
a submodule when one of its path arguments names it, a path inside it or a
directory above it; a run without one collects from the root config's
`testpaths`, else from the root, into every directory no `norecursedirs`
pattern stops. The runs are the runner files' pytest commands, or a bare
`pytest` when there are none. A setting read two ways counts both ways; an
undecodable config or a run's own `-c` config reaches every submodule; a
runner file whose pytest command does not parse is a run without path
arguments; and a path argument that expands a variable (`$1`, `{posargs}`)
names no path. The empty-needle search still rejects a tree with a
submodule, because the startup-context proof needs every Python source, so
that proof is withheld there, as before. The inventory limit
is 200,000 paths, each selected source is at most 1 MB, and a selected read batch
is at most 64 MB. Limits raise errors instead of silently truncating evidence.
Working-tree inventory excludes Git metadata, rejects directory symlinks, and
does not silently skip hidden source trees. It can therefore reject a very
large or uninspectable tree instead of claiming a clean result.

Only an explicitly complete, structurally valid search result may narrow the
runtime-shadow test inventory. An ordinary sequence, capped/unknown result,
malformed path or search failure falls back to the complete inventory. Main's
CLI uses the full inventory and strict batch readers directly.

## Validation status

The author performed source parsing with Python's `ast` module and
`git diff --check` only. No product module was imported, and no local engine,
pytest, gate, dogfood, benchmark or sweep was run. New source tests cover the
listed installation scopes, timing/ownership negatives, relative-import
boundaries, strict snapshot failure behavior, staged provider changes and the
equivalent-provider no-credit invariant. Their results require the authorized
pool receipt for the integrated head; a source review is not that receipt.
