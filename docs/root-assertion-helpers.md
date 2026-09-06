# Repository-root assertion helpers

The root-helper precision change supports this particular extraction:

```python
# tests/test_calc.py
from calc import add
from test_helpers import assert_equal

def test_add():
    assert_equal(add(2, 3), 5)

# test_helpers.py, in the repository root
def assert_equal(actual, expected):
    assert actual == expected
```

The helper must have exactly two required positional parameters and one bare
equality assertion comparing those parameters. The caller must invoke it as a
direct statement in a top-level test function, passing one ordinary call with
literal arguments and one expected literal. Aliased imports and reversing the
equality's operands are supported. The root module must have a test or conftest
role, and an existing sibling module makes the import ambiguous.

The helper module may contain only these transparent definitions and a module
docstring. Definition annotations, decorators, defaults, imports, assignments
and executable module statements are outside this proof. The caller may contain
imports, docstrings and plain top-level test definitions. Each test has at most
one concrete equality assertion or helper call, plus docstrings or `pass`;
arbitrary assertion expressions and companion oracle calls are excluded because
they can execute setup effects. Setup assignments, arbitrary calls and dynamic search-path
changes receive no new credit. Apart from the helper import and the concrete
assertion/call spelling, the caller's AST must remain unchanged. Expected-value
arguments remain visible to the detector. These restrictions also apply to
pre-existing setup code, which can otherwise neutralize a newly imported helper.
This bounded syntax check does not prove arbitrary Python calls free of side effects.

The analyzer preserves the concrete subject and expected value at the call
site. An extraction from an existing test must retain the subject expression;
replacing `add(2, 3)` with a different call does not earn this credit.
Changing the expected argument from `5` to `4` therefore remains an
expected-value rewrite. A file containing an assertion, or an import that is
never called, does not establish that the assertion still runs.

This does not implement general Python import or argument evaluation. Defaults,
decorators, helper coercions, keyword forwarding, local shadowing, calls behind
control flow, dynamic imports and arbitrary `sys.path` changes receive no new
refactor credit. Existing sibling and same-directory relative helper support
continues separately. The analyzer never executes the reviewed code.

## Changes made only to the helper

Removing the assertion must remain visible even when the importing test file
does not change. For a changed root helper that previously met the transparent
equality contract, the CLI and sweep search the analyzed head snapshot for its
module name. Importers absent from the real diff have the same file bytes on
both sides; those bytes are analyzed with the helper's distinct base and head
definitions. Real diff entries are never replaced by this discovery.

Discovery uses one batched search, at most eight candidate importer reads,
and the existing sixteen-read oracle budget shared with helper resolution.
Source reads are limited to one million bytes, and sixty-four search hits are
treated as an incomplete search. Exhausted or unavailable discovery, a read
error, an ambiguous sibling during helper modification, or a root-helper
rename is an engine error (CLI exit `2`), not a clean verdict. These conservative
limits can require manual review in larger repositories. Ordinary unused
imports and comment-only helper changes do not create removed assertions.
Resolution also checks root and sibling package `__init__.py` paths: either
package makes the module target ambiguous. Those absence checks consume the
same sixteen-read budget; a missing package and an unavailable read are distinct.

The strict Git adapter distinguishes grep exit `1` (no matches) from failures;
its blob reader distinguishes a missing path from a failed or incomplete read.
The working-tree adapter reports inaccessible, disappearing, oversized or
outside-repository source instead of silently omitting it. Legacy best-effort
readers retain their previous behavior.

Direct `analyze`/`build_ir` callers can supply optional `root_reader` and
`root_searcher` callbacks with those strict guarantees. Existing `head_reader`
and `head_searcher` callbacks keep their legacy contract and are not silently
trusted for absence-sensitive root discovery. Without the strict callbacks,
new root extraction credit is unavailable; changing a previously transparent
root helper requires the snapshot API and reports an engine error.
