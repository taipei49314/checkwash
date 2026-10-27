# Oracle credit in the 0.10.0 candidate

D-179 replaces text/body/mass-only compensation with bounded static source
context. Proven complete moves, exact duplicates and supported literal table
projections remain; unknown setup, execution effects and dynamic lookup do not
acquire a waiver. Freeze remains effective for assertion-only compensation.
The [integration overview](repair-integration-0.10.0.md) describes the full goal.

Six independently reproduced proof defects were fixed and read back against
18 bounded observations. The final development target recorded 369 passing
checks; its source map is distinct from final integration qualification. These
results neither prove universal runtime equivalence nor accept historical cost.

The initial integration retained eight incompatible old expectations. A later
2026-10-27 delegation led to the independently reviewed, case-specific
[D-185 dispositions](oracle-context-dispositions-0.10.0.md): all represented
program inputs and full old fixture bytes are preserved, while the new
expectations retain the unproved obligations as BLOCK. Two legitimate corpus
refactors remain explicit false blocks. This is not a precision measurement or
release acceptance; final-source checks remain separate. The initial issue is
[#567](https://github.com/taipei49314/checkwash/issues/567).

## Historical pre-disposition movements — exact old/new observations

HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL. 16 static API arms, zero CLI calls; fixture programs were never run.
Old source is frozen 9a5a. Candidate is the copied development working-tree source map in results.json, not a HEAD qualification.
Original .gwcase bytes equal their 9a5a Git blobs. Labels and raw are unchanged; actual per-arm findings and movements are below.

| Case | Observed old → new | Why no proof / retained cost |
|---|---|---|
| bare_bound_then_used_neg | pass → block | OUTPUT_ORACLE_REMOVED: output invoice_total==105 replaced by input data equality; a different strong assertion is not the same obligation. |
| split_rename_genuine_neg | pass → block | SUBJECT_NORMALIZED: sorted(options(...)) can conceal return container/type/order differences; same expected literal and mass do not prove equivalence. |
| unittest_keyword_split_neg | pass → block | SUBJECT_NORMALIZED: keyword assertEqual operands are supported; the remaining changed sorted subject is not proven equivalent. |
| test_split_neg | pass → block | UNKNOWN_CHANGED_SETUP: make_app() becomes make_app(automatic_options=True) for one moved assertion; no source/default proof is supplied by the fixture. |
| subject_pairing_other_subject_known_limit_pos | block → block | UNKNOWN_FIXTURE_REWRITE: two warning tests change fixture/setup/input context; the original independent ASSERT_WEAKENED block remains. Static equivalence of the disappeared units is not established. |
| assert_removed_moved_neg | pass → block | UNKNOWN_ASSERTION_EFFECTS: login calls are reordered across test units; absent source/purity proof, the original unknown prior/following assertion calls cannot be erased from execution context. |
| js_chai_property_moved_neg | pass → block | UNKNOWN_ASSERTION_EFFECTS: isPaid/total calls are reordered across callbacks; no implementation/purity proof is supplied, so the old text-only move label is unresolved conservative cost. |
| merged_parametrize_neg | pass → block | UNKNOWN_DYNAMIC_LOOKUP: literal table/input substitution is retained, but getattr(parse(url), attr) is not assumed identical to direct attribute access; opaque calls can alter builtin lookup. Optional getattr projection was removed after a real independent API counterexample. |

Every row retains exact old/new finding dictionaries, fingerprints, escalators/de-escalators, raw stream hashes and original expectations in immutable-cost-register.json/results.json.
These were unresolved compatibility failures at that historical checkpoint;
the later D-185 ledger records their separate delegated disposition without
rewriting these original observations or claiming a reviewer-approved FP rate.
New bad/legitimate controls remain separately in tests/test_oracle_credit_context.py; their passing results do not waive these historical gates.
The earlier cost-r1 pre-execution source-map failure is retained with ABORT.md; it ran no API arm.
