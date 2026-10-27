# CheckWash stage7: inactive-fixture prototype, not accepted

The active repair goal remains incomplete. Source fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c
and its full fixed-source receipts are preserved in the previous checkpoints.
The original product checkout and previous stage5/stage6 evidence stay frozen.
The last complete remote handoff is e52db89c1d717ce92d46b1dca6d3eb1c98821ef8.

This supplement preserves the first uncommitted inactive-fixture prototype in
`wip-history/pre-inventory-r1`, including complete bytes of all five WIP files.
It is UNSAFE / NOT ACCEPTED / NOT EXECUTED. Read `review/findings-r1.md`:
the first proposal omitted reserved fixture/compiler names and nonancestor
repository collection hooks. Those gaps are not external-plugin limitations.
Never adopt it or infer a passing product state from the backup operation.
An explicit closed inventory and side-correct proof are under development in
`work/checkwash-inactive-fixture`, branch fix/inactive-fixture-oracle-proof-20261027.
Later live edits are not part of this frozen pre-inventory snapshot.

Two external new-test baseline runs used unchanged fbc product source:

- r1: 5 failed / 65 passed, exit1. External test SHA f8f5d54dacd3d1bd789563e513b7d5bc370ebdda7122b9613ddb9d57a0f10eca.
  Its full bytes were reconstructed identically to the hash recorded before
  execution; the separate reconstruction provenance is retained. Two new
  expectations incorrectly demanded overall BLOCK despite separate D1 repair
  evidence. Original results remain, with no retroactive PASS claim.
- r2: 3 failed / 68 passed, exit1. External test SHA 6183818236e4be92c02a1fb3cc1add3719aca14296fdf52118455fd103de4ca4.
  The two new controls inspect absence of move credit instead, and a yield-from
  negative was added. Three real inactive-fixture relocation positives remain
  red. These are different test inputs, not 141 unique passes.

The fixed fbc source manifest remained 51836ac93ce5670644a050f8e3ced2390d377b63bff4b956cc52741b291f9ee5.
No stage7 development implementation has yet been executed in this snapshot.
The source reasoning in review files remains NOT_RUN; AST parsing alone is
not runtime proof. No existing golden/gate expectations were relabeled.

Continue with a closed repository source inventory, BASE/HEAD reconstruction,
reserved binding checks, per-unit inactive fixture proofs, and controlled WIP
tests with full input copies. Full qualification belongs to a later fixed
commit and must not reuse fbc acceptance. JS and #263 remain separate work.

PJU is HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL; no pool investigation, paid/model
batch, merge, tag, publication or downstream repin occurs here. Preserve before
shutdown, and let product work take the time it needs. Stop before 1.0 for Nelson.
