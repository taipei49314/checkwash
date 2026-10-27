# Independent readback of four recorded development runs

The recorded receipts and XML are consistent. This is a readback of PJU Windows/Python 3.11.9 working-tree development evidence, **not a fixed-commit full suite, qualification or acceptance**. The fbc base SHA does not claim that the uncommitted implementation is present in that commit.

| Run | Actual exit | Passed | Failed | XML parent count | XML testcase count |
| --- | ---: | ---: | ---: | ---: | ---: |
| r1 | 0 | 274 | 0 | 274 | 274 |
| r2 | 1 | 179 | 143 | 322 | 322 |
| r3 | 1 | 322 | 1 | 323 | 323 |
| r4 | 0 | 323 | 0 | 323 | 323 |

All four XML files have zero errors/skips, and their suite totals agree with their testcase entries and stdout. These runs use different source/test inputs; their counts are not unique-case totals. All 143 r2 failures contain the existing `runtime-shadow inventory requires both path and byte readers` refusal. They remain failed evidence. The later caller pairing fixes do not weaken that guard. The sole r3 failure is the new bare-parametrize sibling counterexample.

Each run's six complete source copies matches its historical manifest's sizes/hashes and its actual `input-hashes.json`. Each input manifest and tracked-source diff matches the corresponding receipt hash. All receipts retain actual exits, unchanged inputs and `WORKING_TREE_DEVELOPMENT_NOT_COMMIT_QUALIFICATION` provenance.

The r3 and r4 `source.diff` hashes are equal because the helper was untracked. Their complete inputs differ: helper SHA `e13b2ed785958dc56745b7097a806443e638722c0178bd62116cb8a81d448e93` becomes `d3f3be535ebf6deb360d013eb7d0565e3878b73049b5d93a18298fe5ef6a52de`. All other five copied sources are identical. The raw helper copies prove exactly one changed line, adding `node.attr != "parametrize"` to the bare-marker predicate. The preserved helper diff has SHA `f3cbdcfd30dce900467d8ea2ad1273167fc97545a86903cec742bd75dd130818`.

Every ordinary #358 assertion AST is identical to fbc in all four revisions. Removing only the added `search_source_mapping` import and the explicit search/path-list/batch-reader keywords restores the entire original module AST. Its existing PASS expectation was retained. The live six files match r4 copies, and the other 3,081 tracked fbc files match the sealed raw hashes, including protected contracts, gates, strength and existing golden fixtures.

Raw artifact hashes, complete failure identities, XML attributes and source-copy hashes are in `development-readback-r4.json`, SHA `6c4c0113da00cfb59eed71009215b65f401d737cd5d65a191cc348b817e9be29`. The auditor used only standard-library read/hash/XML/AST-as-data operations. No product, fixture, pytest or model execution occurred; no source, expected label or raw receipt was modified.
