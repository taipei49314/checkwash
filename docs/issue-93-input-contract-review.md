# Issue #93: input replacement needs a classification decision

Issue #93 asks for a finding when an existing test changes a subject's input
while retaining its expected answer and production code. A literal, local,
fixture or parameter-table input can all hide a production bug this way.
The current input-keyed expectation comparison deliberately does not treat
an input replacement as an expectation replacement.

Three frozen fixtures require **no findings**, rather than merely excluding
one particular expectation rule:

| Fixture | Replacement | Frozen result |
| --- | --- | --- |
| `tests/cases/expectation_parametrize_input_neg.gwcase:30` | `[50.0, 50.0]` to `[60.0, 45.0]`, expected `105.0` retained | `[]` |
| `tests/cases/param_row_input_edit_appended_neg.gwcase:41` | `[50.0, 50.0]` to `[60.0, 40.0]`, expected `105.0` retained, another row appended | `[]` |
| `tests/cases/subject_argument_replaced_neg.gwcase:22` | `encode_path(s)` to `encode_path(t)`, with distinct unchanged local strings and the expected answer retained | `[]` |

The owner already identified the first conflict in the
[issue comment](https://github.com/taipei49314/checkwash/issues/93#issuecomment-5545946866).
`SPEC.md:278` preserves input-only replacements under the existing expectation
rule. `docs/expected-provenance.md` likewise compares expected answers within
an unchanged input key. `ASSERT_SUBSTITUTED` requires both subject and
expectation changes; `SUBJECT_NORMALIZED` requires wrapping the old subject,
not substituting a distinct argument. Therefore the requested broad rule
cannot be implemented faithfully while preserving all three exact `[]`
expectations.

## Concrete proposed behavior

An opt-in policy would leave the current default behavior intact; it would
not resolve the issue's request for a default blocking check. A default
policy requires maintainer authorization to revise the frozen contract and
the input-only fixture labels, with fresh precision measurements.

For that policy, a separate `SUBJECT_INPUT_CHANGED` finding would keep the
expectation and input concepts distinct. Its bounded predicate would require:

1. The same existing test and the same resolved production callable.
2. The same comparison operator and canonical expected answer.
3. A changed concrete literal argument, resolved through straight-line local
   bindings, supported fixture returns or a bounded literal parameter table.
4. The ordinary production-repair severity policy, including escalation when
   there is no relevant production change.

This would report the three frozen examples above, the direct normalization
example from #93, keyword arguments, and equivalent raise-style comparisons
already represented by the frontend. Renames preserving the resolved input,
new tests, parameter row reorders and pure additions would remain controls.
An arbitrary computed input, ambiguous fixture provider, or changed callable
would not receive invented literal evidence.

Such a rule flags changed coverage; it cannot statically establish that a
changed input conceals a bug. The complete historical sweep must measure
that precision cost before release. The decision must not be hidden by
special-casing the frozen example values or reporting input changes through
an unrelated expectation rule.

No frozen file, gate, fixture expectation or severity policy was changed for
this review. This document does not claim that #93 is resolved.

## Outcome (2026-09-21): adopted, implemented in the T-436 candidate

The maintainer adopted the bounded `SUBJECT_INPUT_CHANGED` policy described
above and authorized revising the three frozen expectations in the same
decision (DECISIONS D-060, estate T-436). The implementation matches the
four clauses: same unit and structurally same stable callable, unchanged
oracle, changed arguments resolved to concrete literals on both sides
(reaching first, then unit bindings, then module constants), and the
ordinary repair-evidence severity path. The literal parameter-table spelling
pairs a vanished row with an arriving one that keeps its answer, refusing
the pairing when the input survives with a changed answer so the row-keyed
expectation rule keeps its #135 event.

The three fixtures listed at the top now expect the new finding instead of
`[]`; each still proves its own rule stays silent on the shape. The
rename-preserving-value, computed-input, shared-producer, reorder and
repair-evidence controls ship as `tests/cases/subject_input_*` fixtures, and
THREATMODEL row 103 records the family with its residuals. The precision
cost is measured by the full historical sweep before release, using the
local release-validation exception explicitly recorded in estate T-436.
The final table path shares the plain-call and stable-provider checks with
the direct argument path; changing the callable cannot manufacture a
same-subject input finding.
