# Additional bounded table carriers

The v0.4.0 candidate recognizes three additional ways to retain the same
ordered sequence of concrete assertions. They use the existing assertion
strength, alignment, repair and severity policies. Expected values remain
visible on both sides and changing a retained input's answer still reports.

* A complete same-file forwarding function can pass each plain positional
  argument exactly once, in its original order, to an imported callable.
  Every use must be a direct call. Rebinding, extra computation, dropped or
  duplicated arguments and ambiguous calls withhold projection. A table may
  bind the result of its subject call to a fresh name used once by the
  assertion; unused or duplicated evaluated calls are not removed.
* An assertion helper may bind one result and attach a literal or simple
  f-string diagnostic. This extension requires every imported subject in the
  module to prove a primitive string result from literal string arguments.
  The source proof permits a single plain function, leading string-local
  assignments, string operations, slices, conditional returns and optional
  standard `re.sub`. Unknown imports, object formatting hooks, mutation,
  user callbacks, shadowed `re` and dynamic format specifications withhold
  the proof. No repository expression is evaluated. The proof has 2,048
  steps and depth 16 in addition to the existing source-size bounds.
* A default-scope, zero-argument fixture can contain complete scalar-string
  assertions followed by a returned imported callable. Direct consumers
  retain the fixture's entire assertion prefix before their own assertions.
  A literal string fixture and local literal string expectations can also
  supply `zip(inputs, expected)` with exactly equal finite lengths. The
  same primitive-source proof establishes that imported code cannot replace
  `zip` or the formatting authorities. Rebinding, truncation, cleanup,
  configured fixture scope and mutable/computed cells receive no credit.

All carriers still require strict snapshots, inert repository startup,
default collection, an unchanged imported-module set and the complete
original input prefix. Pure additions may follow that prefix. A reordered
or missing original assertion is not an equivalent projection.

The exact historical #130 examples FP009, FP016, FP019 and FP021 now pass
under these bounded forms. `tests/test_transparent_table_calls.py` records
their shapes alongside changed-answer, missing-input, rebinding, formatting
and execution-context controls. This does not establish equivalence for
arbitrary helpers, fixtures or dynamic iterables, or relabel historical
benchmark records.

`pytest.approx` over finite numeric literals or a flat numeric sequence may
also be carried in a parameter row or in the assertion. The expected value
and every explicit tolerance remain in the projected assertion; converting
an exact answer to an approximate one retains ordinary weakening detection.
These carriers additionally require unshadowed pytest and closed pure source
for every subject call, because construction during collection can precede
an inline assertion. Dynamic tolerances, approximate subject inputs, unknown
imports and mutating production source receive no projection.
Diagnostic f-strings may format literal containers and a production result
when an import-free source proof establishes only primitive operations on
literal arguments. The grammar includes bounded single-generator list
comprehensions and builtin `zip`; imported callbacks, object constructors,
mutation and formatting expressions remain unsupported. Callable fixture
and zip-fixture carriers retain their narrower scalar-string proof.
