# Ordinary classic consumer: explicit native-field equality proposal

Read-only assessment; NOT_APPLIED / NOT_EXECUTED. Existing fbc self-dogfood
ASSERT_WEAKENED/high and all raw receipts remain immutable. This is not a waiver
or a request to change strength, alignment, an exemption ledger or issue266 names.

The proposed ordinary test change is semantically sound if implemented exactly:
keep dynamic dataclasses.fields(original.side), exclude only the two explicitly
named IR3 enrichment fields, and assert that the resulting set equals the full
17 native field names. Then compare each whole native attribute value against
the standalone frontend side, with ordinary equality, and preserve every
existing separate enrichment/exception-removal/BLOCK assertion.

The 17 native attributes in fbc UnitSide are:
span, assertions, calls, markers, handlers, param_cases, body_hash, bindings,
param_columns, param_rows, param_rows_unknown, collect_ignored, invoked, params,
patches, exclusive_bindings, fixture_producers.

This has an independent test-maintenance benefit: field-specific diagnostics
and an exact schema-membership guard. A field rename/addition cannot silently
pass by keeping a count of17; the set guard fails and requires reviewed
maintenance. `assertions` must remain a full value equality (including every
nested Assertion field), not a count/type/selected-field comparison. Do not
truncate any other list/dict/tuple value either. All prior values are the same
trusted IR dataclass/container values; the intended assertion is the conjunction
of all17 equalities, which is what the existing dictionary comparison expresses.

The original len==17 assertion can be replaced by the stronger exact-name set
guard, not merely removed. The two enrichment assertions must continue to check
the original side's empty fields and the engine side's complete typed proof map
and context, without blanking/deleting those fields. The original exception
oracle and ASSERT_REMOVED/BLOCK obligations must remain.

Changing assertion spelling for those clarity/completeness reasons is ordinary
consumer maintenance. Reordering until self-dogfood turns green, choosing a weaker
comparison, or claiming the spelling proves semantic exemption would be checker
appeasement and is not supported. Whether the fixed checker still reports high
is a future native observation, not a reason to alter the intended assertions.
Keep the old3high receipt regardless of any later result.
