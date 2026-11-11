# v0.12.0 hosted verification after publication: run 43039360146

Label: `HUMAN_AUTHORIZED_GITHUB_HOSTED_NOT_PJU_RECEIPT`. This is hosted
evidence, not a PJU receipt and not a branch required status, and it is
supplementary evidence after publication, not part of v0.12.0's release
evidence (checkwash D-204; `docs/RELEASING.md`, "Hosted release
verification").

Run <https://github.com/taipei49314/checkwash/actions/runs/43039360146>,
attempt 1, of `.github/workflows/release-hosted.yml` at main
`eb4fdab6fbae82da3945b8b2e511445c9630214b`: dispatched from main with the
checkpoint `both` at 2026-11-11T14:31:56Z, completed at 14:50:49Z,
conclusion failure. Its subject is v0.12.0: M
`ffaf4ed86ecc2baeb8cc008487a44d8495da9177`, R
`dfa934519b3639dea689056d3b3ab08a92e45d1c`, A
`532f74ab070a924b23e2cc70e5d0091a05d8401d`, tag object
`6f8b8b7a95f8c6070a0c4bfb1e3ea5a9cb534fe2` and GitHub Release 437647350.

On the three `macos-latest` source legs the whole suite failed: 14 test
entries in `tests/test_collect_pju_release.py` failed, each on the PJU
Action replayer's path check refusing `/var`, a symlink on macOS
(`symlink/reparse point: /var`). Every other job succeeded. checkwash's `docs/releases/v0.12.0-publication-verification.md`
holds the record.

## Contents

Copied from LAPTOP-01AGNPJU through the GitHub REST API between
2026-11-11T15:01:04Z and 15:06:44Z, before the artifacts expire at
2027-02-09T14:31:57Z.

- `artifacts/*.zip`: the run's 15 artifacts, each the bytes of the API's
  artifact download. Each file's size and SHA256 equal the `size_in_bytes`
  and `digest` that `artifacts.json` gives for it.
- `logs.zip`: the run's log archive (`GET .../actions/runs/43039360146/logs`).
- `run.json`, `jobs.json` and `artifacts.json`: the run, its 16 jobs with
  their steps, and its artifacts, as the API returned them at copy time.
- `SHA256SUMS`: the SHA256 of every other file under `hosted/`.

`jobs.json` lists one step as `in_progress` with no conclusion: step 8, the
pyz step, of job 130586951764 (published artifacts, `ubuntu-latest`, Python
3.11). That job's conclusion is success. Its log shows the step's pyz
qualification (283 of 283) and inventory passing, and step 9, which runs
only when step 8 succeeded, ran after it.
