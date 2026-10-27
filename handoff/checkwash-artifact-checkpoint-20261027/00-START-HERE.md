# CheckWash artifact working-backup handoff

**This backup is destined for the verified public repository taipei49314/checkwash. It provides no
private access restriction or ACL. Internal historical PRIVATE/private labels mean only a nonrelease
working snapshot; they do not mean private repository visibility or encrypted/private storage.**

Frozen snapshot UTC: `2026-10-27T01:22:11.561222+00:00`. Code candidate: `1be28ce5de72dcb617818077aaf11e3b1cf7a976`.
[PR572](https://github.com/taipei49314/checkwash/pull/572) is the separately committed draft followup.
The product source is candidate 1be, not this handoff metadata tree's inherited metadata-parent product root.

The fixed candidate has 323 targeted passes. Parent self-check: PASS / exit0 / 0H3W. Integration
self-check: **BLOCK / exit1 / 3H12W**. Four artifact byte identities and the nine selected build/install/
smoke/identity jobs have actual exit0 receipts. These checks do not establish acceptance or release.
Full suite snapshot: `IN_PROGRESS_NO_TERMINAL_ACCEPTANCE_INCLUDED`. Assertion qualifications snapshot:
`IN_PROGRESS_NO_TERMINAL_ACCEPTANCE_INCLUDED`. Their terminal acceptance is not in this package;
no live partial or later result is inferred as PASS. The repair goal remains incomplete.

Archive: [checkwash-1be28ce5-artifact-checkpoint.zip](checkwash-1be28ce5-artifact-checkpoint.zip), SHA256 `eba17306f0e3d221677e1483e464ed25c992b9e021a03c0e71a590c63ec7537f`,
13,769,469 bytes; 125 exact members (112 frozen originals +13 metadata). It preserves the four raw
source/wheel/sdist/pyz artifacts and the seven stage10 #263 read-only analysis files. Stage10 is
**NOT_IMPLEMENTED**; the old fixture supplies no producer and cannot imply add(a,b)=a+b.

[Original artifact restore entry](ARTIFACT-START-HERE.md) and [original manifest](ARTIFACT-MANIFEST.json)
retain their raw bytes, including historical labels. [Previous evidence checkpoint](../checkwash-inactive-fixture-followup-20261027/00-START-HERE.md)
is `815dc12b7786783a7f6004d5360640d37ee49309`. No merge, tag, GitHub Release, PyPI publication or new 1.0 grant occurs here.
Nelson must decide before 1.0. Backup publication and product publication are separate.
