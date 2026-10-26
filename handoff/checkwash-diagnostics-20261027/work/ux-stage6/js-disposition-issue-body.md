At fixed source **fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c** (0.10.0 / IR3), the existing normal arm of `tests/test_js_liveness.py::test_a_unit_moved_into_a_skipped_block_earns_no_move_credit` expects PASS/info for moving a bare `it("computes", () => { expect(total()).toBe(5); });` into a new plain `describe("moved", ...)` in another file. The actual result is BLOCK/high. Its original expected output remains unchanged.

Bounded static API observations at the exact fbc source distinguish the cause:

- bare → bare and identical describe → identical describe controls: PASS/info;
- bare → new describe: BLOCK/high; nonempty proof keys differ because the suite envelope is observable module/control context;
- hook, local binding, custom describe, function/this and skipped-wrapper controls: BLOCK/high.

A proposed whole-module/single-unit wrapper projection was **rejected and never applied**. Although it would make the original arm pass, it also grants ASSERTION_MOVED/info to both unchanged test bodies below when only the wrapper is added:

```js
const s = expect['get' + 'State']();
if (s['current' + 'TestName'].startsWith('moved')) return;
expect(total()).toBe(5);
```

```js
if (getTestName().startsWith('moved')) return;
expect(total()).toBe(5);
```

The unchanged fbc analyzer reports BLOCK/high for both; the unapplied prototype reports PASS/info for both. These are static analyzer results, **not JavaScript runtime execution or an observed runtime escape**. The observers are unknown. D-179 requires proof rather than assuming that unknown observers/calls cannot see suite context; a finite identifier denylist is insufficient. The original `total()` likewise has no closed implementation in this fixture.

Six prototype comparison API calls and twelve baseline diagnostic calls were recorded on LAPTOP-01AGNPJU / Python 3.11.9, HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL; fixture-program executions, pytest and CLI calls in those diagnostics were zero. The prototype source hash is `464435753edb7dc6a2dc2c652584f4c1f5b9a675838dd3fd8850da6bcd4ec36d`.

Required follow-up: either supply a closed, bounded proof that the relevant calls/runner context are unchanged and insensitive to this wrapper, or have the maintainer explicitly dispose of the existing compatibility expectation. Do not erase suite context, relabel the existing expected output, weaken gates/strength/alignment, or declare this positive control fixed from an unsafe green prototype. This issue records an unresolved ordinary positive control separately from #567 and #568; it does not waive the integration candidate's other failures or authorize release/1.0.

