# Python environment conditions and existing assertions

This page describes an unreleased 1.0 preparation candidate. Published 0.7.0 does not include this repair.

The candidate reports ASSERT_WEAKENED when a previously unconditional, unchanged bare assertion gains a supported environment condition. Supported forms are a direct `import os`, a literal `os.environ.get(KEY) == VALUE` or `!= VALUE` comparison with a string value, and either a single assertion wrapper or a bare early return before the assertion. The finding contains the old assertion and the new condition, with source spans. The detector emits warn; existing gates decide whether it blocks.

Identical assertions in both branches, or a direct surviving identical assertion without an intervening state change, retain their verification obligation. Existing conditions and validation before return do not acquire this new finding. Definitions, calls and other potentially effectful statements prevent proof that an outside assertion is equivalent.

This finite analysis does not resolve arbitrary predicates, aliases, helper or fixture effects, nested control flow, getenv, default arguments or unittest assertion methods. It does not evaluate the caller's environment or prove the runtime truth of a condition. JavaScript support is a separate work package. A clean result does not guarantee coverage of those forms.

`--emit-ir` adds three fields to each Assertion object:

| Field | JSON type | Default for older constructor payloads |
| --- | --- | --- |
| unconditional_obligation | boolean | false |
| environment_guard | string or null | null |
| environment_guard_span | two integer character offsets or null | null |

False with no guard means no affirmative obligation proof. Spans use the existing normalized-source offset convention. Older Assertion payloads can omit these fields when constructing the candidate's objects; consumers that reject extra JSON keys need compatibility checks before upgrading. Emitted IR bytes change, including default fields. Findings JSON v2, exit codes, strengths and gate rules retain their existing contracts.
