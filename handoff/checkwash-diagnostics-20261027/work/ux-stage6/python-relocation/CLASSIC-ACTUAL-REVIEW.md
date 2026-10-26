# Actual separate-worktree classic review

State: PASS_BOUNDED_ORDINARY_CONSUMER_CONTRACT_REVIEW.
Evidence: `classic-consumer-review.json`, SHA256
`448d7764f6f1c8ce46950b31c5f46f66fb8ab69efe27b75c1398f8873b120965`.
The pure standard-library reader exited0 with45 checks; product/pytest calls0.

At readback the separate worktree HEAD was fbc, with exactly the ordinary
classic test modified. All3084 captured development members match its current
bytes. The development input map6580ef36 differs from frozen fbc map51836ac9
only for tests/test_classic_raises_additions.py. Thus no product, strength,
alignment, gating, existing golden label or other expected verdict is changed.

The model AST defines17 native fields plus exactly the two enrichment fields.
The new literal-name set is complete and unique; every native field has one
same-name whole-attribute equality in declaration order. `assertions` is compared
as the whole nested value, not as set/count/type. Dynamic dataclasses.fields
enumeration and the exact two-field enrichment exclusion are unchanged.

After removing only the old count/dictionary equality and the new exact-name
guard/17 direct equalities, the **entire module AST is identical**. That includes
the original exception-oracle BLOCK and ASSERT_REMOVED assertions, original
fixture strings/parameterization, every negative control, and all separate IR3
proof/context/map enrichment assertions.

Existing native classic-targeted-r1 JUnit/stdout says31passed, no failures/errors/
skips, exit0; stderr is empty and captured source diff hash matches. This was an
unchanged **working-tree development** run. It is not qualification for a new
commit, a new full-suite result or evidence that self-dogfood turns green.
The semantic assessment remains independent of the checker's future reaction.
Original fbc self-dogfood3high and all original receipts must remain immutable.
