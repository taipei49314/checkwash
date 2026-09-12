# Parameter input roles in the unreleased family candidate

The row replacement detector owns changed answers that disappear with their
old inputs. A count-preserving replacement is not automatically an honest
input edit. The original comparison for surviving input keys runs first:
changing or swapping their answers still produces expectation evidence.

Two optional source checks distinguish narrower input changes. Both require
unchanged assertion and test-body structure, paired before/after evidence,
and bounded literal parameter tables. Unsupported or incomplete evidence
leaves the ordinary detector in charge.

A nested decorated function may itself be the produced object consumed by
the assertion. When the same uniquely bound object flows into the subject on
both sides, arguments of its evaluated construction decorators can have an
input role, including a parameter also used as the expected value. An unused
definition or unselected local container entry cannot supply that role.
Visible rebinding, input/object mutation and unsupported setup invalidate
the optional proof.

This is the existing syntactic input-consumption convention used for direct
calls such as `sut(expected)`. It does not prove that a callee mathematically
depends on every argument. For example, an unchanged `@ignore(expected)`
decorator that simply returns its function can still be a syntactic input
when that function is used. This no-op-callee limitation is explicit; the
proof does not establish preserved test execution or semantic equivalence.

A separate check pairs a disappeared row with an arrived row only when the
expected cell copies the same active input projection on both sides. The
supported projection is a whole inert scalar or one literal string-keyed
dictionary field. Other input cells and fields must retain their canonical
values. The selected path must actually feed the subject; an unused field
cannot stand in for an active input. Each concrete row occurrence is consumed
at most once, and every unproved disappearance retains the replacement rule.
This permits an identity input rewrite such as `(1, 1)` to `(2, 2)` without
claiming that the two tests cover the same concrete input. It does not exempt
the general transformation `(1, 2), (2, 4)` to `(2, 4), (3, 6)`.

Dictionary ordering is normalized only for unique literal string keys and
supported inert values. Plain, unchanged standard Enum declarations have a
separate authority check; arbitrary properties, dynamic enum definitions,
namespace replacements or ambiguous repository module shadows do not gain
constant-member credit. Fixture-indirect parameter transformations cannot
be treated as direct literal input rows.

The optional pass accepts at most 250,000 source bytes and 40,000 AST nodes
per side, 128 rows per table, 64 visible provider dependencies and 48 cached
snapshot reads. Source parsing, unsupported expressions or exhausted proof
bounds withhold this evidence. The pass is attempted only when an existing
test's parameter tables changed; it never executes repository Python.

No rule ID, severity, assertion strength, alignment parameter or production
repair credit changes. Exact source, executed regressions and retained
failures are recorded in the review PR and EC T-326 delivery evidence.
