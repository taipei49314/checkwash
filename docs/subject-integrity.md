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
Missing required blobs, malformed paths/records, unsupported selected source,
submodules or incomplete batches fail with `EngineError`. The inventory limit
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
