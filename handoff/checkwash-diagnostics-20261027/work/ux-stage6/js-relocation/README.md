# JS describe relocation: rejected unsafe proposal

**Final disposition: `REJECTED_UNSAFE_NOT_APPLIED`.** The proposed envelope projection is not a safe D-179 repair. Keep the current finding and the existing fixture expectation pending [issue #570](https://github.com/taipei49314/checkwash/issues/570); neither the product nor expected labels were changed here.

The source observed by the baseline captures is `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`. PJU evidence is `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. These diagnostic results do not qualify later source revisions, including the separate ordinary consumer proposal in PR #569.

## Observed root cause

The normal `describe` case in `tests/test_js_liveness.py::test_a_unit_moved_into_a_skipped_block_earns_no_move_credit` moves the exact `it("computes", () => { expect(total()).toBe(5); });` declaration from a bare module into `describe("moved", ...)`. The baseline P1 captured before/after inputs, including the old-file `// moved to b` comment, match that original fixture exactly. The full-suite failure is therefore reproduced by the baseline static analyzer capture, not inferred from source alone.

The fbc proof is present on both sides. It differs because `_javascript_context` retains the surrounding declaration, binding and control environment outside the unit span. The bare context key is `100beca457a1967e7519ae24fef2a8d5047b033008f56d676253b04029948c61`; the wrapped key is `9c1b54ade18087ca36f68a9e2569797c272eb481cee9531c23425f84799a4edc`. The unit text is identical, but the surrounding `describe` declaration is new. This is neither a missing snapshot reader nor an absent proof. The original fixture provides no implementation of `total()` from which independence of suite metadata could be proved.

The eight JS baseline records show bare-to-wrapper `BLOCK/high`, bare-to-bare and same-wrapper controls `PASS/info/ASSERTION_MOVED`, and hook, local binding, custom `describe`, function-wrapper/`this`, and skipped-wrapper variants `BLOCK/high`. The skipped case additionally loses credit through existing liveness handling. Four Python arms in the same 12-call capture were not audited here.

## Why the proposal is rejected

The preserved proposal recognizes a whole module consisting of one plain global `describe`, one unit, literal titles and zero-argument arrow callbacks, then projects away that wrapper for the environment proof. This proves a narrow syntax shape; it does not prove that opaque calls inside the unit cannot observe the changed suite/name context. A finite denylist of `getState`, `currentTestName`, `this` and similar tokens cannot close that gap.

Root captured three input pairs under both fbc and an exact copy of the proposed module. All three changed from baseline `BLOCK/high` to prototype `PASS/info/ASSERTION_MOVED`: the native positive, a split-string `expect['get' + 'State']()` / `s['current' + 'TestName']` observer, and an opaque `getTestName()` observer. The latter two contain a conditional early return. Their assertion proof maps are empty, while their whole-unit context keys become equal under the projection. The existing complete-unit credit route accepts a valid empty assertion map together with an equal whole-unit proof; the unsafe projection therefore supplies the decisive false equivalence. Changing all empty-map credit or gating would disturb other complete-unit cases and does not repair this proof.

These are **six static analyzer calls**, explicitly `MIXED_RUNTIME_PROTOTYPE_NOT_FBC_QUALIFICATION`. No JS fixture, Jest/Vitest runner, pytest or product CLI was executed for them. The observations establish analyzer de-escalation despite an unclosed metadata dependency; they do not establish that a real JS runtime skipped an assertion. The prototype native-positive uses the inert old-file comment `// moved` rather than the original `// moved to b`; its before unit and arrival module match the original. It is not claimed to match the entire original input byte set.

No safe product patch is recommended in this packet. A future implementation needs a closed call-effect/metadata proof or an explicit human contract disposition. Additional token denylisting, silently relaxing D-179, or changing fixture labels to obtain green results is not adopted.

## Evidence and preservation

- `captured-evidence-readback.json` contains the original fixture hash, eight baseline raw hashes, full findings/fingerprints, proof keys, unit spans, derived outside environments, six prototype raw hashes and both capture receipts.
- `REJECTED-UNSAFE.json` is the latest authoritative disposition. It supersedes the original proposal's optimistic prediction.
- `proposal-oracle-credit.diff` remains byte-for-byte SHA-256 `75a8d8e4983c15abe159b5e0c7cf8427cd123c67379ceb1fa8db88de813f7b51`.
- `proposed-oracle_credit.py.txt` remains SHA-256 `464435753edb7dc6a2dc2c652584f4c1f5b9a675838dd3fd8850da6bcd4ec36d`. Its creation-time inert provenance is preserved. Root later executed an exact external copy in the clearly identified mixed-runtime diagnostic; it was never applied to the product checkout.
- `probe-arms.json` preserves the initial 11-arm proposal. Baseline diagnostics cover its three exact positive inputs and five negative families with some different hook/shadow/indent bytes. Additional N6/N7/N8 remain `NOT_RUN`; the whole 11-arm proposal is not reported as executed.
- This agent performed only standard-library reading, restricted literal AST extraction, hashing and report generation. Product/API calls, pytest calls and fixture execution by this agent: **0**.

The original proposal, root capture files, product source, tests, contracts and expected labels are unchanged. `MANIFEST.json` seals this directory's final files, excluding itself. No further files are to be added here after freeze.
