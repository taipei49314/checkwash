# v0.13.0 hosted release verification: runs 43910068162 and 43940303262

Label: `HUMAN_AUTHORIZED_GITHUB_HOSTED_NOT_PJU_RECEIPT`. Hosted evidence kept
beside the PJU release-stage receipts under EC POLICY
`checkwash-release-hosted-verification-20261111` and checkwash D-204
(`docs/RELEASING.md`, "Hosted release verification"). Not a PJU receipt and
not a branch required status.

Subject: CheckWash `v0.13.0`, release merge `M` =
`7d45814211bbb458d310607b3a241761c7d5f7e3`, release PR head `R` =
`c37a341f733a3f4ed13d7e427132e5267bd5324c`, Action commit `A` =
`9ada8cfaa618b002b5d0d829c7ddbe1b8e8ae638`, annotated tag `v0.13.0` object
`f8ff8258d2e2a9a68488d5c1894f1518dfe02bce`, and GitHub Release `447438064`.

1. **Checkpoint `source-at-M`**: run
   <https://github.com/taipei49314/checkwash/actions/runs/43910068162>
   (`source-at-M-43910068162/`), dispatched from `main` at
   `2026-11-16T16:40:19Z`:
   - `attempt 1`: five source legs (`ubuntu-latest` Python 3.11/3.12/3.13,
     `macos-latest` Python 3.12/3.13) and the Linux composite Action passed;
     `macos-latest` Python 3.11 (job `133449434654`) was cancelled by GitHub
     before any runner acquired it (`runner_name: ""`, `steps: []`, annotation
     `"The job was not acquired by Runner of type hosted even after multiple
     attempts"`). All 7 uploaded attempt-1 artifacts, logs and metadata are
     retained here.
   - `attempt 2` (`gh run rerun 43910068162`, whole-run rerun per
     `RELEASING.md`): conclusion `success`. All 6 `macos-latest` and
     `ubuntu-latest` Python 3.11/3.12/3.13 source legs (`23,358` test cases and
     `67` subtests, `0` failures, `0` errors), all source qualifications and
     inventories, the 6-way + PJU `SIX_LEG_SHA256` corpus comparison
     (`f57e1ba64023d7fb947d8fa287c82a31248d953a5c92c3a29004c173ec01ede8`), and
     the Linux composite Action at `A` (`exit 0`) succeeded. All 8 attempt-2
     artifacts, logs and metadata are retained here.
2. **Checkpoint `published-artifacts`**: run
   <https://github.com/taipei49314/checkwash/actions/runs/43940303262>
   (`published-artifacts-43940303262/`), `attempt 1`, dispatched from `main` at
   `2026-11-16T19:31:59Z` after `publish-assets` succeeded and before PyPI
   deployment approval: conclusion `success`. Identity, Release `447438064`
   record check, and all 6 `macos-latest` and `ubuntu-latest` Python
   3.11/3.12/3.13 published-artifact legs succeeded. All 8 attempt-1 artifacts,
   logs and metadata are retained here.

Each `.zip` under `artifacts/` equals in byte length and SHA256 the
`size_in_bytes` and `digest` recorded by the GitHub REST API in
`artifacts-after-attempt-*.json`. `SHA256SUMS` lists the SHA256 of every other
file under `hosted/`.
