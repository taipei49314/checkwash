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
In particular, a structurally unchanged ordinary assertion keeps its native binding
owner. Additive evidence requires an assertion helper or literal loop on
either side, or changed assertion syntax such as literal-to-local extraction.
The comparison uses the original assertion AST, preserving names and literal
contents while ignoring formatting, comments and redundant parentheses.
A function called only to obtain the actual result is not an assertion
helper. Resolving its call expression and an existing local expected value
does not transfer ownership to this channel or prove its external execution
environment unchanged.

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
an inert strict startup snapshot and a closed visible source graph spanning
the caller, helper, ordinary imported modules and package initializers.
Every function body in that graph must fit the effect-free subset, so an
import-time or subject-call mutation of builtins or `math.prod` withholds the
proof. Missing imports and alternate package-prefix modules/initializers are
unknown. The graph admits literal module bindings and plain functions using
primitive expressions, local assignments, branches and loops. Attribute or
subscript writes, dynamic calls, dunder hooks and unproved external imports
are rejected. In-place arithmetic is limited to independent numeric-literal
accumulators; a parameter, parameter alias or loop-row mutation is not pure.
Aliases retain authority only without rebinding. Callable parameters and
fixture-bearing callers receive no constant-call proof; subject arguments
must be primitive literals. For `math`, every relevant repository module
shadow must be absent.

The graph checks at most 32 modules with the existing 65,536-byte and
4,096-node source limits. Authority may make at most 64 additional snapshot
reads, sharing the source cache with ordinary provenance. Exhausting that
optional proof budget preserves the unknown expression and its finding.

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
snapshot reads. Subject calls remain opaque. Loop iterators and an
expected-value helper can request bounded return-expression substitution.
An expected helper additionally requires the closed source-graph and startup
authority described above before its return can prove the same answer. An
existing expected helper's changed return remains visible even when its
caller and assertion are unchanged.

The v0.4.0 candidate also retains fresh-local expected calls, literal-only
f-strings and `pytest.approx` expressions across zero to two additional local
aliases. It keeps existing literal/derived findings as the owner of their
assertion spans. An unresolved external golden fixture remains an independent
oracle, not a concrete replacement answer. Same-file scalar-return fixtures
and their bounded scalar dependencies can identify the subject inputs only
under inert startup, default collection and absent repository pytest shadows.
Mutable fixtures, configured providers and unknown fixture bodies remain
unsupported. Literal table carriers accept fresh row-cell aliases; aliases
resolve back to the original cell before checking repeated object use.

The new regressions exercise the actual analysis pipeline, unchanged-caller
discovery, row identity, native-owner controls, JSON arrays and bounds.
This change does not relabel historical benchmark outcomes or declare the
larger consolidation family complete.

## Conversions, unevaluated calls and JavaScript (#226)

The rulings of 2026-10-03 and 2026-10-04 (226.Q1-Q3) give both frontends one
definition of an expected value that is not a plain literal. It is one of
three things.

**A conversion of one literal**, from a fixed set, which folds to its value:
Python's `float(<literal>)` and `Decimal(<literal>)`, and JavaScript's
`Number(<literal>)`. A spelling folds only where its name can be nothing else:
`float` while the module binds that name nowhere, `Decimal` when a top-level
import of the decimal module is the one binding of the name it is spelled
with, and `Number` while no scope declares it and no write reaches it.
`Number` folds a number literal or a string holding a plain decimal numeral.
The fold calls only those constructors, on a bounded literal; a signalling
NaN does not fold. The folded value is the assertion's literal (`right_value`)
and this channel's answer, so EXPECTED_VALUE_CHANGED compares values:
`78.75` -> `float('75')` reports "expected value rewritten 78.75 -> 75.0", and
`78.75` -> `Decimal('78.75')` reports nothing. Python literals compare as
Python's `==` compares them, folded or not, so `1` -> `1.0` is no change and
`0.1` -> `Decimal('0.1')` is one (the float is not exactly one tenth).
JavaScript records one canonical Number, which already compares that way.

**A name or call the file binds**: an import, a same-file function or a
declaration this channel reads. Its change is EXPECTATION_DEFINITION_CHANGED
through this channel, as Python has reported it (`78.75` -> `OTHER` reads
"78.75 -> app.OTHER"). The JavaScript port reads an equality's expected value
the same way, by substitution: an import becomes its module and export
(`./total.OTHER`), a `const`, `let` or `var` the read reaches becomes its
initializer, resolved in turn, and a function or class the file declares
stays a call. A pair on one subject, which must be a call after substitution
as in Python, whose resolved values differ, while either side read such a
name, is an event: `toBe(make(1))` -> `toBe(make(2))` reads
"./total.make(1) -> ./total.make(2)". The port reads no other module's source,
follows eight levels of initializers, and leaves a template literal that
interpolates unresolved.

**A call checkwash neither folds nor resolves**: its callee's root is a name
the file never binds, a builtin or global outside the fold set (`int`,
`round`, `parseFloat`) or a name bound nowhere. A literal replaced by one, or
one rewritten into another on the same subject, is EXPECTED_VALUE_CHANGED
"expected value replaced by an expression checkwash does not evaluate (78.75 ->
int('75'))". A Python star import may bind any name, so no callee beside one
is unbound; an expression over the subject's own input stays
EXPECTED_VALUE_DERIVED's.

Not decided here: a name or call replaced by a literal is read in Python
(#60) and not in JavaScript ([#292](https://github.com/taipei49314/checkwash/issues/292)).
