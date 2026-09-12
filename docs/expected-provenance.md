# Bounded expectations through helpers and literal loops

The additive expectation provenance channel keeps expected values visible
when ordinary assertion helpers receive literal actual arguments, bind a
local expected expression, or consume rows from a finite literal loop. It
also detects replacing a literal answer with a newly bound, different local
literal. Extracting the same literal remains unchanged.

The source pass substitutes arguments and reaching straight-line bindings;
it never imports or executes repository code. Same-file helpers and uniquely
resolved test/conftest module helpers are supported, including positional,
keyword and literal-default arguments. Helper-local definitions are retained
alongside substituted formals. Literal-return table helpers may supply a
loop iterator. An available complete snapshot search can discover unchanged
tests importing a changed helper, so a helper-only edit remains reviewable.

Events are paired by test unit, concrete subject/input and comparison operator.
Expected values are compared as a multiset **within each input key**, never
as a global answer bag. Whole-row reorder, padding, unchanged duplicates and
input-only changes do not rewrite an existing key's answer. An answer swap
between two input keys, including a swap accompanied by padding, does.

Events add `EXPECTATION_DEFINITION_CHANGED` evidence and use the existing
repair/severity gates. They do not replace native assertions, alter alignment
or assertion strength, or provide equivalence credit. Existing native binding
findings and already-concrete root-helper literal findings keep their owner.

The pass is bounded by 65,536 source bytes and 4,096 AST nodes per module,
48 new source reads per discovery/projection pass, depth eight, 2,048
processing steps and 128 events per side;
each literal loop has at most 64 rows. Unsupported statements or exhausted
processing limits discard the unit's additive events, retaining ordinary
frontend behavior. Dynamic iterators, decorated helpers, varargs, conditional
control flow and ambiguous imports receive no invented provenance. Direct
nonliteral expected expressions remain with the existing detectors; the
helper channel can retain their substituted defining expression without
executing repository code. A separate closed literal language proves equal
results for primitive arithmetic, comparisons, conditional selection and
slices. `len` and `math.prod` additionally require unshadowed lexical imports,
an inert strict startup snapshot and, for `math`, no repository module shadow.
Aliases retain authority only without rebinding. Callable parameters and
fixture-bearing callers receive no constant-call proof.

The closed language permits 128 steps, depth 16, 256-bit integers, finite
floats, sequences of at most 64 items and strings/bytes of at most 4,096
characters. Unknown calls, unavailable authority, oversized literals or
different results do not become equal: the original expression or the
different literal remains in the input-keyed evidence. Rebound helper names
and local reads before their first
binding are declined rather than borrowing stale functions or module values.

Ordinary native literal assertions use their existing IR without another
AST pass. Helper discovery skips root modules already reviewed by the
existing root-helper channel, and projection reuses that channel's strict
snapshot reads. Subject calls remain opaque; only a loop iterator requests
bounded literal-return helper expansion.

The new regressions exercise the actual analysis pipeline, unchanged-caller
discovery, row identity, native-owner controls, JSON arrays and bounds.
This change does not relabel historical benchmark outcomes or declare the
larger consolidation family complete.
