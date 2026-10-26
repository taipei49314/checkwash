# CheckWash maintenance follow-up: backup only

Source / code source: `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`. Candidate version **0.10.0**, IR3 / findings2.
`backup_state=TERMINAL_BACKUP`; purpose `BACKUP_ONLY_NOT_ACCEPTANCE_NOT_RELEASE`.
Acceptance state: **NONPASS**. No product publication was performed.
Version 1.0 requires Nelson's explicit decision.

The ordinary `1ffe283d7d947fecc426dea99323b0a2620a9482` → fbc self-check remains **BLOCK / exit 1**,
with critical 0, high 3, warn 9.
The original findings, exact fingerprints and source comparison are retained under
[completed/selfdogfood/](completed/selfdogfood/README.md). Raw filenames acquire `.txt`
only for safe backup transport; RAW-EXPORT-MAP.json records their original names/hashes.
No waiver, exemption, expected-label change or gate override is added by this backup.

| Validation role | Actual captured state | Actual exit |
|---|---|---|
| qualification_source | TERMINAL | 0 |
| qualification_wheel | TERMINAL | 0 |
| qualification_pyz | TERMINAL | 0 |
| full_suite | TERMINAL | 1 |

Only completed stage5 outer receipts supply terminal exits. A missing terminal receipt
is not PASS, and a directory does not prove a process is still live. Independent audit
exit 0 means evidence consistency only: a full-suite exit 1 remains NONPASS permanently.
The index does not predict test counts or borrow old8a qualification results.
Bundle state: **COMPLETE**. The complete evidence ZIP is included; terminal backup completion still does not mean acceptance.
See [checkpoint.json](checkpoint.json) and [MANIFEST.json](MANIFEST.json) for exact copied bytes.

The frozen8a backup, its five archives and 22 failing tests are a **historical baseline**
at [d158 legacy entry](https://github.com/taipei49314/checkwash/blob/d158ec02aac9c0c19751d0475f935b533e3d03f7/handoff/checkwash-core-010-20261027/00-START-HERE.md).
Those archives/results are not current fbc validation and are not recopied here.
Restore the fbc Git source and its required history before continuing; an optional
sealed source ZIP preserves bytes, not Git objects. Do not rewrite the earlier backup.

All recorded local execution identifies the actual PJU host/runtime and is marked
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. This backup does not establish other OS,
unexecuted runtimes, formal release-bridge or published-check coverage. Preserve
all failures, #567/#568 decisions and publication boundaries. Do not run subjects,
paid/model/history batches or change host-global settings to complete this handoff.
