"""Redact an existing benign qualification receipt; does not run qualification.

Reads only sibling evidence. Writes only inside this public directory.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re

PUBLIC = Path(__file__).resolve().parent
SOURCE = PUBLIC.parent
source_receipt_path = SOURCE / "receipt.json"
source_receipt_bytes = source_receipt_path.read_bytes()
source_receipt = json.loads(source_receipt_bytes)
source_receipt_sha = hashlib.sha256(source_receipt_bytes).hexdigest()
python_path = source_receipt["commands"][0]["argv"][0]
python_home = python_path.rsplit("\\", 1)[0]
asset_path = source_receipt["checks"][0]["detail"]["path"]
asset_dir = asset_path.rsplit("\\", 1)[0]
replacements = [
    (python_path, "<PYTHON>"),
    (python_home, "<PYTHON_HOME>"),
    (asset_dir, "<ASSET_DIR>"),
    (str(SOURCE), "<WORKSPACE>"),
    (str(SOURCE.parent.parent), "<SESSION_WORKSPACE>"),
]
private_tokens = [(value, "<LOCAL_USER>") for value in [os.environ.get("USERNAME", "")] if value]
private_tokens += [(value, "<LOCAL_HOST>") for value in [os.environ.get("COMPUTERNAME", "")] if value]
private_tokens += [(str(source_receipt[key]), "<INTERNAL_REFERENCE>") for key in ("task", "claim") if source_receipt.get(key)]
patterns = []
for value, placeholder in replacements:
    variants = {value, value.replace("\\", "/"), json.dumps(value)[1:-1]}
    for variant in variants:
        patterns.append((variant, placeholder))
patterns.sort(key=lambda pair: len(pair[0]), reverse=True)


def redact_text(text):
    for value, placeholder in patterns:
        text = re.sub(re.escape(value), lambda _match, p=placeholder: p, text, flags=re.IGNORECASE)
    for value, placeholder in private_tokens:
        text = re.sub(r"(?<![\w])" + re.escape(value) + r"(?![\w])", lambda _match, p=placeholder: p, text, flags=re.IGNORECASE)
    return text


def redact(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


raw_public = PUBLIC / "raw"
raw_public.mkdir(exist_ok=True)
files = {}
for path in sorted((SOURCE / "raw").iterdir()):
    if not path.is_file():
        continue
    original = path.read_bytes()
    published = redact_text(original.decode("utf-8")).encode("utf-8")
    target = raw_public / path.name
    target.write_bytes(published)
    files[path.name] = {
        "published_path": "raw/" + path.name,
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "published_sha256": hashlib.sha256(published).hexdigest(),
        "original_bytes": len(original),
        "published_bytes": len(published),
        "sanitized": original != published,
    }

published_receipt = redact(copy.deepcopy(source_receipt))
for key in ("task", "claim"):
    published_receipt.pop(key, None)

assert len(published_receipt["commands"]) == 33
assert len(published_receipt["checks"]) == 15
for command in published_receipt["commands"]:
    for stream in ("stdout", "stderr"):
        name = command[stream].replace("\\", "/").rsplit("/", 1)[-1]
        original_hash = command.pop(stream + "_sha256")
        assert original_hash == files[name]["original_sha256"], (command["name"], stream)
        command[stream] = files[name]["published_path"]
        command[stream + "_original_sha256"] = original_hash
        command[stream + "_published_sha256"] = files[name]["published_sha256"]
        command[stream + "_sanitized"] = files[name]["sanitized"]

for network in published_receipt["network"]:
    name = network["raw"].replace("\\", "/").rsplit("/", 1)[-1]
    original_hash = network.pop("sha256")
    assert original_hash == files[name]["original_sha256"]
    network["raw"] = files[name]["published_path"]
    network["original_sha256"] = original_hash
    network["published_sha256"] = files[name]["published_sha256"]
    network["sanitized"] = files[name]["sanitized"]

published_receipt["sanitization"] = {
    "is_publication_of_existing_evidence": True,
    "new_qualification_runs_performed": False,
    "source_receipt": {
        "logical_path": "<WORKSPACE>/receipt.json",
        "sha256": source_receipt_sha,
        "availability": "Unmodified original retained by the maintainer; omitted from the public bundle because it contains private local paths.",
    },
    "source_qualification_driver": {
        "logical_path": "<WORKSPACE>/qualify.py",
        "sha256": hashlib.sha256((SOURCE / "qualify.py").read_bytes()).hexdigest(),
        "included": False,
    },
    "method": "Case-insensitive substitution of local absolute-path prefixes, including JSON-escaped and forward-slash forms; removal of internal coordination identifiers; local user/host token redaction if present. Preserve all other log bytes, including newline style and empty streams.",
    "placeholder_meanings": {
        "<WORKSPACE>": "Isolated qualification directory containing venv, scratch repository, raw logs, and receipt.",
        "<PYTHON>": "Explicit CPython 3.11.9 executable used for these Windows runs.",
        "<PYTHON_HOME>": "Base installation directory of that CPython interpreter.",
        "<ASSET_DIR>": "Directory containing the previously downloaded official v0.2.12 pyz.",
        "<SESSION_WORKSPACE>": "Parent workspace outside the isolated qualification directory, if referenced.",
        "<LOCAL_USER>": "Private local user token, if referenced.",
        "<LOCAL_HOST>": "Private local host token, if referenced.",
        "<INTERNAL_REFERENCE>": "Internal coordination identifier, if referenced in a log.",
    },
    "hash_semantics": "*_original_sha256 identifies the unchanged private raw bytes captured during the original run; *_published_sha256 identifies the sanitized bytes included here. A matching pair means that stream required no edits. The publication is not a byte-identical replacement for the original private receipt.",
    "unchanged_evidence": ["33 command records", "15 check records", "commands and arguments except local path substitution", "asset versions and complete digests", "source URLs", "UTC start/end times", "observed/expected exits", "durations and timeouts", "results and recorded limitations"],
}
published_receipt["interpretation_addendum"] = {
    "blocking_exit_1": "NOT RUN; the new run exercises benign exit 0 and invalid-input exit 2 only.",
    "invalid_revision_json_contract": "Both surfaces return exit 2, human-readable stderr, and empty stdout even when --format json is selected.",
    "doctor": "Canonical local workflow recognized; no branch-protection or merge-enforcement attestation.",
    "additional_not_run": ["SARIF service upload", "full 0/1/2 contract qualification"],
}
write_json(PUBLIC / "receipt.json", published_receipt)

summary = f'''# checkwash v0.2.12: installed-asset qualification

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

The original receipt is retained by the maintainer, outside this public bundle, as `<WORKSPACE>/receipt.json`. Its SHA-256 is **`{source_receipt_sha}`**. The public receipt's `sanitization.source_receipt` and the file inventory anchor the publication to that original. The bundle contains no venv, wheel, pyz, or target executable. The included `build_public.py` only transforms existing evidence files; it runs no package, target code, or qualification command.

## Limits

**NOT RUN:** blocking/exit-1 paths; demo, benches, sweeps or adversarial fixtures; target code or tests; Python 3.12/3.13; Linux/macOS; remote Actions; branch-protection or actual merge-blocking enforcement; real participant onboarding; SARIF service upload. Historical CI is separate and was not evaluated in this run.

This evidence establishes this Windows Python 3.11.9 benign installation subset. It does not establish the full 0/1/2 contract, detector effectiveness, adversarial coverage, refactor false-positive rates, cross-platform qualification, or 1.0 readiness.
'''
(PUBLIC / "SUMMARY.md").write_bytes(summary.encode("utf-8"))

manifest = {
    "schema_version": 1,
    "source_receipt_sha256": source_receipt_sha,
    "published_receipt": {"path": "receipt.json", "sha256": hashlib.sha256((PUBLIC / "receipt.json").read_bytes()).hexdigest()},
    "published_summary": {"path": "SUMMARY.md", "sha256": hashlib.sha256((PUBLIC / "SUMMARY.md").read_bytes()).hexdigest()},
    "publication_builder": {"path": "build_public.py", "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
    "command_count": len(published_receipt["commands"]),
    "check_count": len(published_receipt["checks"]),
    "captured_file_count": len(files),
    "changed_file_count": sum(row["sanitized"] for row in files.values()),
    "new_qualification_runs": 0,
    "files": list(files.values()),
}
write_json(PUBLIC / "SANITIZATION.json", manifest)

# Publication integrity checks only: no installed executable, target code, tests,
# or subprocess is invoked by this builder.
assert source_receipt_path.read_bytes() == source_receipt_bytes
for path in PUBLIC.rglob("*"):
    if not path.is_file() or path.suffix == ".py":
        continue
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), path.name
    for value, _placeholder in private_tokens:
        assert not re.search(r"(?<![\w])" + re.escape(value) + r"(?![\w])", text, flags=re.IGNORECASE), path.name

print(json.dumps({"commands": manifest["command_count"], "checks": manifest["check_count"], "raw_files": len(files), "sanitized_raw_files": manifest["changed_file_count"], "original_receipt_sha256": source_receipt_sha, "published_receipt_sha256": manifest["published_receipt"]["sha256"], "new_qualification_runs": 0}, indent=2))
