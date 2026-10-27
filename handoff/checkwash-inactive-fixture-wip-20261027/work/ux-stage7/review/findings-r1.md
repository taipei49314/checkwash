# Independent source review: inactive fixture integration

Status: BLOCKED_ON_SOURCE_FINDINGS. This is a source review, not a product
execution, prototype, compilation or pytest result. The reviewer changed no
existing fixture, expectation, protected contract, helper or root integration
file. An explicitly authorized new reader-test module was written before the
subsequent freeze; it is NOT_RUN by this reviewer and has not been changed since
the freeze. Root owns development captures and their source maps.

## B1 — changed-side observations could be erased (source repair read back)

The initial new reader used chain_sides' single-pass whole-pair replacement.
For a rename old→new plus an explicit added/recreated old path, record ordering
could erase either the real BASE old bytes or HEAD recreated bytes and return
known absence. This violates the side-correct callback contract independently
of whether a final verdict happened to change.

Root's revised independent per-side observation map was read back: actual bytes
beat inferred rename absence; conflicting actual bytes/explicit absence raise
ValueError lazily on optional read. Old chain_sides/conftest behavior is not
modified by this repair. Both old and new mapped paths have side keys, so the
unchanged HEAD reader is used only outside the map. Source-level issue addressed;
new owned permutation/conflict tests remain NOT_RUN by this reviewer.

## B2 — rejected reads escaped cache/budget (source repair read back)

The initial reader inserted cache entries only after type/size/total checks.
Repeated modules/D10 calls could repeatedly read the same oversized, invalid or
failed unchanged support file without charging the attempted path budget.

Root's revised reader reserves an unknown sentinel before the external read,
counts the attempt, charges actual bytes before size refusal, and rethrows
unknown without rereading. After exhausting the byte budget no new root read
occurs. This does not pretend the first oversized response was never read.
Source-level issue addressed; the new negative-cache controls remain NOT_RUN.

## B3 — reserved pytest fixture name accepted (pending helper repair)

Helper57b9 _fixture/prove accepts a function named request with the canonical
request argument and first-false branch. All other admitted module/producer/unit
conditions can hold, so the helper can reach certificate creation. Pytest rejects
the registered fixture name request while importing/collecting the module.

This was confirmed by reading the actual installed pytest9.1.1 source, not by
running the represented fixture: `_pytest/fixtures.py:1374–1380` computes the
registered name and calls fail when it equals request. The exact source is at
`C:/Users/nelson/AppData/Local/Programs/Python/Python311/Lib/site-packages/_pytest/fixtures.py`.
Reject that name before creating a certificate. An arbitrary inactive branch
does not turn an invalid registration into a collected live arrival.

## B4 — AST-only binding validity is incomplete (pending helper repair)

The consumer ImportFrom alias check accepts identifier __debug__, and the pure
callee grammar can similarly admit that parameter name. Python rejects binding
that name during compilation. An identifier check plus ast.parse is not a
compilation-validity certificate. This is a source-level counterexample, not a
new executed witness.

The [Python3.11 reference](https://docs.python.org/3.11/reference/simple_stmts.html#the-assert-statement)
states that assignments to __debug__ are illegal; [ast.parse documentation](https://docs.python.org/3.11/library/ast.html#ast.parse)
explicitly separates AST parsing from scoping/compilation validity. The exact
[CPython3.11.9 compiler](https://github.com/python/cpython/blob/v3.11.9/Python/compile.c#L2380)
rejects __debug__ Store bindings. Cover admitted import aliases, fixture/function
names and producer parameters/bindings; do not compile or execute subject code
as a workaround.

## B5 — nonancestor repository collection plugin is invisible (blocking)

_startup reads only the selected test's ancestor directories plus root/src.
It has no inventory/search authority. OwnMarks(tree) therefore cannot know that
an unrelated collected subtree contains a repository collection hook.

A concrete unexecuted source witness is:

- tests/hooks/conftest.py defines pytest_collection_modifyitems and adds slow
  only to items whose path is the new moved location;
- tests/hooks/test_smoke.py causes that conftest to be loaded during ordinary
  default collection;
- selected tests and the closed total producer are otherwise the admitted #358
  source, before and after, in the same parent directory.

Adding those two snapshot paths does not change any read/identity that helper57b9
queries. It can therefore issue the same unmarked/inactive certificate. Yet the
repository hook can mark the new item and activate its own autouse skip fixture.
The actual installed pytest9.1.1 `_pytest/main.py:871–874` invokes
pytest_collection_modifyitems for the full collected item list.

This is repository source visible to the strict snapshot, not an ambient
external plugin that the contract explicitly excludes. The current engine's
ancestor-only startup hash does not supply the missing closed inventory either.
Require explicit closed collection/bootstrap inventory (or equivalent trusted
authority) and refuse unknown repo hooks/startup; a read-only callback cannot
prove absence at paths it never discovers. The helper author agrees this is a
substantive missing precondition. No source was changed during r1 freeze.

## Integration properties checked without a remaining finding in those hunks

- The primary closure captures side_index as a lambda default, and D10 fixes
  the callback to side1; there is no loop-variable late-binding bug.
- Non-request reflection restrictions remain before the new helper.
- The helper and oracle context share the same AST; exact request IDs are
  checked, and every qualname independently requires a valid certificate.
- The complete fixture statement remains in the environment; the helper's
  fixed signature/body grammar also binds its supported fixture shape.
- Empty fixture_scope expands to no extra tuple elements, retaining the old
  default proof-key construction. The new domain adds a named scope tag.
- The helper's128-path/64KiB/1MiB reader counts absence probes, validates strict
  bytes, caches admitted paths and binds actual path/hash identities. Import
  closure/arguments are not represented by a pair of purity booleans alone.
- Unknown, partial, marked or malformed per-unit certificates do not supply
  proof. Existing liveness, credit spending and freeze paths are unchanged in
  the reviewed diff.

These bounded checks do not approve the whole change while B3–B5 remain open.
