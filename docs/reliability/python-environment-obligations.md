# Python environment conditions and existing assertions

This page describes an unreleased 1.0 preparation candidate. Published 0.7.0 does not include this repair.

The candidate reports ASSERT_WEAKENED when unchanged bare assertions lose previously guaranteed verification attempts behind a supported environment condition. Supported forms are a direct `import os`, a literal `os.environ.get(KEY) == VALUE` or `!= VALUE` comparison with a string value, and either an assertion wrapper or a bare early return before assertions. The finding contains the old assertion and the actual condition, with source spans. The detector emits warn; existing gates decide whether it blocks.

Preservation depends on how many old verification attempts remain guaranteed. One old assertion can be retained by identical assertions in both branches or by a direct surviving identical assertion without an intervening state change. Two old assertions becoming one in each mutually exclusive branch retain only one guaranteed attempt and produce a loss finding. Shared credit is spent once across matched old obligations; removed assertions retain their separate removal finding. Existing conditions and validation before return do not acquire this new finding. Definitions, calls and other potentially effectful statements prevent proof that an outside assertion supplies equivalent credit.

This finite analysis does not resolve arbitrary predicates, aliases, helper or fixture effects, nested control flow, getenv, default arguments or unittest assertion methods. It does not evaluate the caller's environment, prove operand purity or runtime condition truth, or solve correlations between separate guards. Counts describe syntactic validation attempts when reaching the finite region. JavaScript support is a separate work package. A clean result does not guarantee coverage of unsupported forms.

`--emit-ir` adds four optional fields to each Assertion object:

| Field | JSON type | Default for older constructor payloads |
| --- | --- | --- |
| unconditional_obligation | boolean | false |
| environment_guard | string or null | null |
| environment_guard_span | two integer character offsets or null | null |
| environment_obligation_count | four-element array or null | null |

The first three presence-credit fields retain their meanings and defaults. False with no guard means no affirmative presence proof. Spans use the existing normalized-source offset convention.

The count witness is `[binding_epoch, minimum_count, actual_guard, actual_guard_span]`. Epoch and count are integers; guard and span are string/integer pair or null. It groups normalized full assertion text within an epoch. Every member repeats the same group count: consumers must not sum those repeated values. Outside and complementary copies retain the group's actual guard in this witness even when their older presence fields clear it. Null means unknown count evidence, including older construction payloads; it does not mean zero. Epoch and count must be nonnegative integers, excluding booleans. A guard and its span must both be null or a string and an ordered pair of nonnegative integer offsets. Valid tuple and JSON-array witnesses are accepted; incomplete or malformed witnesses are treated as unknown and retain the existing pair-rule fallback.

Older Assertion payloads can omit these optional fields when constructing the candidate's objects. Consumers that reject extra JSON keys need compatibility checks before upgrading. Emitted IR bytes change, including default fields. Findings JSON v2, exit codes, strengths and gate rules retain their existing contracts. Collection adds a direct-body scan and source whitespace normalization; ordinary assertions request no new expression parse or structural dump. Native cost qualification remains separate from source review.
