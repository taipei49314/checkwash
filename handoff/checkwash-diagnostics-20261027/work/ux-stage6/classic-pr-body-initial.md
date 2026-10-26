The native IR preservation test now names all 17 complete attribute equalities and checks the exact native-field schema. This makes coverage visible and makes a schema addition/removal fail explicitly; the two IR3 enrichment fields retain their separate checks, and the exception-removal assertions and negative controls are unchanged.

Independent AST and byte readback found exactly one changed ordinary test file; all detector code, existing fixture expectations, gates, strength and alignment settings are unchanged. The follow-up is separate from the frozen fbc integration candidate in #566.

Validation at **15ac804593bc41db8f904e7921667bd6c276fa9a**, LAPTOP-01AGNPJU / Python 3.11.9 / HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL:

- Fixed-source existing module: **31 passed, exit 0**; all 3,084 physical files match the reviewed development snapshot and the commit blobs.
- Ordinary self-dogfood against fbc: **BLOCK / exit 1, 3 high** (two ASSERT_SUBSTITUTED, one EXPECTED_VALUE_CHANGED).
- Ordinary integration-range self-dogfood against 1ffe: **BLOCK / exit 1, 3 high / 9 warn** (one classic ASSERT_SUBSTITUTED and the two existing issue266 TEST_DISABLED findings).

The semantic coverage review does not waive these detector findings. Keep this PR in draft for review; no exemption is added. Full-suite and source/wheel/pyz qualification at this new commit are **NOT_RUN**; the fbc receipts remain historical and are not relabeled. No merge, version/tag/Release/PyPI publication or downstream re-pin; Nelson decides before 1.0.

