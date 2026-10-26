# Stage 4: read-only triage of eight ordinary failures

State: **READ_ONLY_TRIAGE_COMPLETE — FAILED SUITE REMAINS**.

The frozen source is `8a8941dc2d7c581715a0f6f196c00da6c55f084b` at
`C:/Users/nelson/Documents/Codex/2026-10-26/1-00-start-here-md-c/work/checkwash-ux`.
The comparison source is `1ffe283d7d947fecc426dea99323b0a2620a9482`.
LAPTOP-01AGNPJU, Python 3.11.9;
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`.

The actual native full suite remains **exit 1: 22 failed, 21055 passed,
25 skipped, 67 subtests passed**. The reviewed reader returned audit exit 0
because the evidence agrees, not because the suite passed. Native XML has
21169 report counts and 21102 distinct parent cases; the extra 67 are not
additional parent collections. All 22 exact failed nodeIDs agree with
stdout, all skip messages remain available in the native readback, and the
3084-file capture map equals the complete source seal. The current source
was independently read back as clean at 8a with identical bytes.

The readback is `final/full-suite-311-r1/independent-readback.json`, SHA256
`89ee94bc17caec0b79a80834fed1228643e68eb61cf7f01879bb40e329f5b177`.
It retains `COMPLETE_FAILED_SUITE`, actual suite exit 1 and all 22 failures.
This document covers eight ordinary tests only. It does not dispose of the
eight unchanged golden labels, the four corpus/gate adapter failures, or
the two packaging/STATE failures.

## Evidence boundary

`selected-native-failures.json` retains the exact eight native nodeIDs and
failure texts, verified against the original native XML. The two long
`classic_raises` parameter IDs remain complete there. `receipt.json` retains
14 read-only Git commands and raw blob bytes for the seven affected test
files at both fixed sources. All seven files are byte-identical between
1ffe and 8a, and the currently read test bytes match 8a. Relevant 8a
implementation/contract sources are copied under `source/` with hashes.

No product, fixture, pytest or modified judge was executed for this triage.
No source, test expectation, golden label, protected gate or original raw
receipt changed. An old assertion describes the unchanged expected contract;
this read-only step did not rerun 1ffe and does not invent a new baseline
PASS receipt. Source explanations below are static reasoning; where native
failure output did not print a complete finding vector, none is invented.

## Eight-row assessment

| Ordinary case | Existing assertion and native 8a observation | Assessment and next named scope |
|---|---|---|
| `test_classic_raises_additions::test_added_literal_rows_retain_exception_removal_and_native_units`, capture variant | Lines 34–35 already established exception evidence, BLOCK and ASSERT_REMOVED. Line 38 then requires the enriched engine `UnitSide` to equal the standalone frontend side. Native failure says the 17 old fields are identical and only `oracle_context`/`oracle_assertion_contexts` differ. | **Definite IR3 consumer migration.** Keep all 17 native fields exactly equal, separately verify the two engine enrichment fields and their SHA/key shape. Do not remove the exception/BLOCK/assert-removal assertions or erase the new fields from product IR. |
| Same test, direct-expression variant | Same earlier assertions passed; only whole-UnitSide equality fails for the two new proof fields, with a different legitimate context digest. | **Same consumer migration**, separate parameter row retained. A raw parser has no engine startup context and correctly keeps these optional fields empty. |
| `test_root_oracles::test_helper_only_assertion_removal_discovers_unchanged_importer` | Lines 221–225 establish BLOCK, ASSERT_REMOVED at `tests/test_calc.py`, severity high, original call text and unchanged search. Line 228's exact six-read list fails: native reports three extra reads, first `tests/conftest.py`. | **Reader-observer contract migration**, not an observed lost detection. D-179 additionally probes startup for proof; source reasoning identifies `tests/conftest.py`, `tests/__init__.py`, `__init__.py`. Preserve the detector's old changed-module-chain boundary separately from proof probes, original BLOCK/high, reverse-search and read-budget negatives. |
| `test_issue223_conftest_request_side::test_an_importer_the_engine_adds_unchanged_reads_no_chain` | BLOCK and ASSERT_REMOVED at the importer already passed at lines 421–422. Line 425 requires the only conftest read to be `conftest.py`; native also records `tests/conftest.py`. This test does **not** assert the finding's severity. | **Reader-observer contract migration.** Make D-179 proof-startup probes explicit without silently granting detector-chain/skip semantics to the unchanged importer. Preserve the existing denial/budget controls and main finding assertions; do not claim this unit measured high when it did not. |
| `test_issue263_string_conditions::test_tests_moved_under_a_class_mark_with_a_string_condition_are_relocated` | Line 229 expects PASS; native observes BLOCK. Its helper supplies no strict root reader. The fixture also moves top-level tests into a new class with `self`, `pytestmark` and a new bound `skipif(...)` call. | **Unresolved ordinary positive cost; not a proven implementation violation.** Missing root context alone is not the complete explanation: current proof also binds class/argument/module context and rejects that nonliteral module binding. A consumer-only root snapshot change cannot be promised to make this PASS. Preserve the expectation pending narrow safe-proof work or explicit maintainer disposition. |
| `test_issue358_own_mark_guards::test_a_test_moved_under_the_gate_keeps_its_move_credit` | Line 336 expects PASS; native observes BLOCK. The test already supplies both head and root readers. Its module includes an autouse fixture using `request.node.get_closest_marker(...)`. | **Unresolved ordinary positive cost**, not a missing strict-reader adapter. The current helper rejects module/helper `request` and decorated fixture context. D6's own-mark liveness fact and D2's two-sided context proof are different obligations. Preserve the expected positive until safe proof or an explicit cost decision; do not flip it to BLOCK merely to green the suite. |
| `test_js_liveness::test_a_unit_moved_into_a_skipped_block_earns_no_move_credit`, active-describe/outcome0 | Lines 233–245 expect a live arrival to produce PASS/TEST_DISABLED info; native observes BLOCK. The `describe.skip` sibling passed its existing BLOCK/high assertion in this same native suite. | **Unresolved ordinary positive cost.** Top-level-to-new-active-describe changes the lexical environment retained by D-179. No missing JS root-reader adapter is involved. Keep the active positive expectation pending finite wrapper-equivalence proof or disposition; retain the skipped-arrival negative. |
| `test_js_test_obligations::test_moving_a_test_out_of_a_ci_directory_is_not_a_workflow_removal` | Lines 102–104 expect PASS, CI_WORKFLOW_TOUCHED/warn and no high findings; native fails the first PASS assertion with BLOCK. Its BEFORE bytes import `{ total } from "./value"` while moving `.github/workflows/value.test.ts` to `src/value.test.ts`. | **Ordinary positive-fixture premise migration.** The canonical producer changes from `.github/workflows/value` to `src/value`. A true same-producer relative import plus closed roots can isolate the original role/CI purpose; retain the old same-spelling/different-target shape as a negative. Neither the full current finding vector nor success of the proposed fixture has been executed here. |

## Source / contract explanation

The IR3 additions are at `src/checkwash/ir/model.py:292–293`.
`SPEC.md:1259–1263` and `DECISIONS.md:316–324` define their empty state as
unknown and explain that standalone old IR has no inferred context.
Engine context enrichment is consequently an intentional extra fact, not
a mutation of the 17 native UnitSide fields tested by the two classic rows.

`engine.py:1713–1767` performs the new proof startup pass, including ancestor
package initializers and conftest context. It runs after ordinary parsing
and the original fixture/marker attribution. The two read-list failures
still observed their intended original blocking detector result. Their
literal claim that an unchanged importer makes no startup read is now too
broad. A maintenance patch must distinguish proof-only reads rather than
removing the old semantic protections. In particular, the new proof pass
uses existing chain caches/read limits (`engine.py:885–945`); future bounded
controls should retain the established refusal/budget behavior. This triage
did not run a new failure/budget counterexample and does not label that
source concern as an observed extra regression.

`oracle_credit.py:91–96` rejects module/helper request/context names;
`:114–143` withholds unsupported class/module/decorator environments;
`:180–205` binds class and complete arguments. Engine `:1727` also withholds
Python startup proof without a root reader. These are concrete reasons why
the issue263/358 positives cannot be called straightforward snapshot-adapter
maintenance. `DECISIONS.md:263–293` explicitly retains those bounded costs,
but does not itself accept these newly observed ordinary-positive failures.

For the JS rows, the independent report is
`qualification/fullsuite-triage-js.md`, SHA256
`c57f28d9ca8a073e388c714f342ab47e8a3090b396ebae75d2463c2ee3e71e46`.
Its evidence JSON is SHA256
`d2294cac8e7b4b1917b016702f4fb7fc2357ccc9dd3bfa737d7e125e12bdcfcb`.
It traces the new describe environment and the supervised-role rename
expansion with different relative-import targets. It separates observed
BLOCK from inferred TEST_DISABLED/proof routing when native output did not
print the complete findings.

## Disposition

Four rows have definite metadata/read-observer consumer maintenance; one
needs a positive fixture that actually preserves its producer. The other
three remain explicit semantic-positive compatibility costs. None of these
eight native failures alone demonstrates an implementation violating D-179,
and that statement does not make any failed gate pass or prove universal
runtime equivalence.

Root requested inert next-stage proposals for classic IR3 enrichment,
startup-probe observer maintenance and a genuine same-producer CI move.
Those proposals must be outside this frozen stage4 packet, keep the original
judge/golden files untouched, and preserve the three undecided positives.
Any later adoption/validation needs a new source/run identity after the
complete 8a backup. This report, original failures and the 22-failure suite
remain unchanged evidence; no fixture is relabeled and no exception is added.
