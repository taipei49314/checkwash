# Decision log

Entries D-001 to D-140, everything up to and including the v0.8.0 release
entry, are in [DECISIONS-archive-1.md](DECISIONS-archive-1.md). They moved
there unchanged on 2026-10-20, when this file had passed 1,000,000 bytes,
checkwash's source byte limit, above which it sets a documentation file
aside unread (F40). The archive keeps the line numbers they had here: read
against `94953c83`, the last commit before the move, a reference
`DECISIONS.md:N` with N up to 10833 is `DECISIONS-archive-1.md:N`. Any
other line reference written before the move reads against that commit.
Entry numbers do not change, and new entries are added here.

Entries D-141 to D-172 moved unchanged at v0.9.0 publication to [DECISIONS-archive-2.md](DECISIONS-archive-2.md), except its prescribed archive title and single-line provenance; old line references read against release commit d6eda4f6.

Entries D-173 to D-187 moved unchanged at v0.10.0 publication to [DECISIONS-archive-3.md](DECISIONS-archive-3.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 10069979.

Entries D-188 to D-196 moved unchanged at v0.11.0 publication to [DECISIONS-archive-4.md](DECISIONS-archive-4.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 34555301.

Entries D-197 to D-201 moved unchanged at v0.12.0 publication to [DECISIONS-archive-5.md](DECISIONS-archive-5.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against tag commit 532f74ab, where the file is the same as at release merge ffaf4ed8.

Entries D-202 to D-213 moved unchanged at v0.13.0 publication to [DECISIONS-archive-6.md](DECISIONS-archive-6.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against tag commit 9ada8cfa, where the file is the same as at release merge 7d458142.

Entry D-214 moved unchanged at v0.13.1 publication to [decision log archive 7](DECISIONS-archive-7.md), with the prescribed archive title and provenance. References written before the move retain their line numbers at release tag commit 62656df812372c085b4d32c7864fcdfaccd0318a.

## D-215 (2026-11-22): v0.13.1 post-publication verdict baseline

The [publication record](https://github.com/taipei49314/checkwash/blob/69bc20b28fd23a3070c3ef8a7115642e7f62ecdc/docs/releases/v0.13.1-publication-verification.md) binds the release to merge `5e2a89ef0d447ae6e08c289f4a3357325b7286e9`. The tag peels to Action commit `62656df812372c085b4d32c7864fcdfaccd0318a`. The public `checkwash.pyz` is 1,079,499 bytes with SHA256 `0a987325c6f738129f5dbdc1e0287cfeab40517342b46df80707cccff8dd2839`.

The [Step 9 proposal](https://github.com/taipei49314/checkwash/blob/64aa06f031a444865be888ba24a06432d878ff2c/proposal/receipt.json) ran on pins commit `69bc20b28fd23a3070c3ef8a7115642e7f62ecdc` on LAPTOP-01AGNPJU, Windows CPython 3.11.9, `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. Its receipt SHA256 is `89209c81f45c9a5434e896985c6958ac1a2f6148bc66051b27b73d84b406ffcb`. The gate ran 159 T1 and 26 T3 cases, with 161 block to block and 24 pass to pass. It reported zero case movements. The sole failure, `acceptance-baseline`, identified the v0.13.0 header in the existing acceptance file. The gate proposed zero accepted entries. The existing 161 baseline-blocked IDs, 26 T3 hashes and 71 canary block-to-pass IDs matched.

The disposition advances the baseline tag, version, peeled commit, public zipapp size and digest, and changes the acceptance header to v0.13.1. The separately reviewed rotation PR requires its own release-stage PR receipt, including a fresh download and full gate, and final maintainer merge confirmation.
