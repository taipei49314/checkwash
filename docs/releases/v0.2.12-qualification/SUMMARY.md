# checkwash v0.2.12: installed-asset qualification

**PASS within this benign scope:** Windows, CPython **3.11.9**. The original run recorded **33 commands and 15 checks**, all with expected results and no timeouts. Run interval: **2026-09-05T19:38:24Z–19:38:41Z**. Every subprocess had a 60-second timeout.

The official PyPI wheel was downloaded, compared with [version-specific PyPI metadata](https://pypi.org/pypi/checkwash/0.2.12/json), and installed without dependencies into an isolated venv. The previously downloaded [official release pyz](https://github.com/taipei49314/checkwash/releases/download/v0.2.12/checkwash.pyz) matched its expected digest.

| Artifact | SHA-256 |
|---|---|
| `checkwash-0.2.12-py3-none-any.whl` | `66baf258949791ef5f773463d5227857e5f248b5d159e0497048da87736532b7` |
| `checkwash.pyz` | `1fed863c3d8d240a3da63eed5ae01954f60fe31b53ffb6a1ecef7a267193baf3` |

Installed distribution and imported module both report **0.2.12**, with the import inside the isolated venv. Both `checkwash` and legacy `greenwash` console scripts point to `checkwash.cli:main`. Runtime requirements are empty; the only requirement in package metadata is the optional development dependency `pytest>=8`. The venv's existing pip and setuptools were not upgraded.

| Verification | Installed CLI and official pyz |
|---|---|
| Version and help | Exit 0; version 0.2.12 |
| Unchanged committed range, JSON/SARIF | Exit 0; pass/empty results |
| README-only benign diff, JSON/SARIF | Exit 0; pass/empty results |
| Invalid revision with `--format json` | Exit 2; error on stderr and empty stdout |
| Canonical workflow inspected by doctor | Exit 0; 0 problems and 0 warnings |

The isolated repository has two commits and no remote. Only README wording changes; production and test files are unchanged and were never executed. Doctor recognizes the local three-step pinned workflow and explicitly says it cannot verify whether the check is required. The inspected Action pin is **v0.2.11**; the installed CLI and pyz are **v0.2.12**. No remote workflow or branch rule was changed or exercised.

## Evidence and sanitization

[receipt.json](receipt.json) preserves every command and check, its result, duration, timeout, asset provenance, and links to [the sanitized captured streams](raw/). [SANITIZATION.json](SANITIZATION.json) inventories all 67 captured files: 66 stdout/stderr streams plus the official PyPI JSON response. Empty streams are included.

Private local absolute paths are replaced by readable placeholders such as `<WORKSPACE>`, `<PYTHON>`, and `<ASSET_DIR>`. Private user/host tokens, if present, are redacted; internal coordination references are omitted. No command was rerun to create this publication. Other captured log bytes, including line endings, are preserved.

For each stream, `original_sha256` identifies the **unmodified original capture**, and `published_sha256` identifies the **sanitized file included here**. Equal hashes mean no edits were needed. The receipt uses the corresponding `stdout_*` and `stderr_*` fields. These hashes make the transformation auditable; they do not make a sanitized file identical to its private original.

The original receipt is retained by the maintainer, outside this public bundle, as `<WORKSPACE>/receipt.json`. Its SHA-256 is **`6130e88bb6afefb4da7b4137378c67fcf78f65893874ce78b040f1bda255baeb`**. The public receipt's `sanitization.source_receipt` and the file inventory anchor the publication to that original. The bundle contains no venv, wheel, pyz, or target executable. The included `build_public.py` only transforms existing evidence files; it runs no package, target code, or qualification command.

## Limits

**NOT RUN:** blocking/exit-1 paths; demo, benches, sweeps or adversarial fixtures; target code or tests; Python 3.12/3.13; Linux/macOS; remote Actions; branch-protection or actual merge-blocking enforcement; real participant onboarding; SARIF service upload. Historical CI is separate and was not evaluated in this run.

This evidence establishes this Windows Python 3.11.9 benign installation subset. It does not establish the full 0/1/2 contract, detector effectiveness, adversarial coverage, refactor false-positive rates, cross-platform qualification, or 1.0 readiness.
