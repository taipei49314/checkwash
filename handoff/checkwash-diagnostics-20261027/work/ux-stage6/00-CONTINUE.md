# CheckWash follow-up: diagnostics and separate ordinary-test consumer

The repair goal remains **active / incomplete / NONPASS**. The preceding goal
turn made progress by pushing and independently reading back the complete
fbc backup at `ec4b80ac162d1fbdb73c329ee39d87992d4fbafe`. This supplement records
further concrete work; it does not redefine completion around these results.

## Two source identities

- Integration candidate: **fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c**, package
  0.10.0 / IR3 / findings2, draft [PR #566](https://github.com/taipei49314/checkwash/pull/566).
  Its complete [previous backup](https://github.com/taipei49314/checkwash/blob/ec4b80ac162d1fbdb73c329ee39d87992d4fbafe/handoff/checkwash-maintenance-20261027/00-START-HERE.md)
  retains full-suite **15 failed / 21,064 passed / 25 skipped / 67 subtests passed**,
  self-dogfood **BLOCK / 3 high / 9 warn**, and three distribution qualifications
  of the same **283 controls each**, all exit0. They stay fbc evidence.
- Separate consumer-only proposal: **15ac804593bc41db8f904e7921667bd6c276fa9a**,
  branch `fix/explicit-native-ir-assertions-20261027`, draft
  [PR #569](https://github.com/taipei49314/checkwash/pull/569), parent=fbc.
  It changes one ordinary test file to an exact 17-name schema guard and 17
  complete attribute equalities. The count17 guard becomes an exact17-name
  expected set; the original native field values still compare in full.
  No detector, .gwcase/corpus verdict expectation, gate, strength or alignment
  changes. Independent AST review proves the remaining module,
  enrichment checks, BLOCK/assertion-removal controls and negative controls
  unchanged. It is **not merged into fbc**.

At 15ac the fixed-source existing module has **31 passed / exit0**. Its ordinary
self-check against fbc is **BLOCK / exit1 / 3 high / 0 warn**; the integration
range against 1ffe is **BLOCK / exit1 / 3 high / 9 warn**. Full-suite and
source/wheel/pyz qualifications at 15ac are **NOT_RUN**. Do not borrow fbc's
qualification or claim the explicit assertions cleared self-dogfood.

## New observed diagnostics

`final/bounded-context-r1` captures **12 static analyzer API calls**, source and
ending=fbc, unchanged inputs51836, fixture-program executions0, pytest0, CLI0.

- #263 original and the same input with a closed root both BLOCK/high. The
  closed root makes the old side's proof known, while the class/marker side
  still has no proof. Providing a root alone is insufficient.
- #358 original BLOCK/high despite known startup; the module-wide request
  guard leaves proofs empty. A separately named no-gate pure-move control
  passes/info. This does not authorize deleting the original fixture.
- JS bare-to-new-describe BLOCK/high; bare-to-bare and same-wrapper moves
  PASS/info; hook, local binding, shadow, function/this and skip controls BLOCK.

`js-prototype-r1/observations` adds **6 static API calls**, explicitly mixed
runtime: unchanged engine plus a frozen **unapplied** proposed proof module
SHA464435753edb7dc6a2dc2c652584f4c1f5b9a675838dd3fd8850da6bcd4ec36d.
The proposal makes the original JS control pass, but also grants ASSERTION_MOVED
to two unknown title-observer cases. It is **REJECTED_UNSAFE / NOT_APPLIED**.
No JavaScript fixture/runtime execution or observed runtime escape is claimed.
[Issue #570](https://github.com/taipei49314/checkwash/issues/570) records the
required closed call/runner-context proof or explicit compatibility disposition.
Finite observer-name denylists do not close unknown calls.

Each raw JSON retains complete findings, fingerprints, UnitSides, proof maps,
startup lookups and exact input hashes. The diagnostic capture's exit0 means
the observations were captured, not that the product or all cases passed.
The two pytest runs are a 31-test WIP snapshot and the same 31-test fixed
commit check, not 62 unique tests. The two self-check CLIs are separate from
the 18 static diagnostic API calls.

## Remaining work and continuation

Read `completion-audit/report.md`, the Python rootcause/proposal/readbacks,
the JS rejection/readbacks and the ordinary-consumer self-check readback.
The original 14 requirements have implementations and bounded controls; this
is not 127 empirical passes. Three normal-refactor controls and two refactor
corpus identities still need safe proof/product work or individual disposition.
The eight unchanged golden cases (#567), four corpus identities (#568) and
self-dogfood findings remain visible. Not every failed case is human-only.
Do not relabel expected outputs or use unsafe proof projection to obtain green.

Restore the two exact source revisions and required Git history separately.
The handoff metadata branch inherits its parent's product root and must never
be treated as either product revision. MANIFEST and SELECTION map original
task paths to transport paths; `.py.txt` files are bytes to restore deliberately,
not instructions to execute automatically. Keep failed reader attempts as well
as their corrected readbacks. Proposals retain their inert/rejected status.

PJU remains the authorized default host, with actual host/source/runtime/exit
and raw evidence recorded as HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL. No
Tuesday-noon expiry or pool investigation is introduced. This supplement adds
no paid/model/history batch, release collector, host-global change, merge,
tag, release, publication or downstream re-pin. **Nelson decides before 1.0.**
The 07:30 instruction is a remote-preservation deadline before changing work
location; product acceptance is not accelerated by it.
