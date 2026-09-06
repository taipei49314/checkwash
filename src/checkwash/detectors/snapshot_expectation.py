"""The file-backed form of EXPECTED_VALUE_CHANGED (issue #129)."""
from checkwash.findings import Finding, change_identity, make_change_fingerprint
from checkwash.ir.model import IR


def detect(ir: IR) -> list[Finding]:
    # Preserve the existing snapshot co-change policy, including its broad
    # treatment of unrelated or opaque production changes. A comment-only
    # production edit does not qualify as an implementation change.
    if ir.globals.prod_symbols_changed or ir.globals.prod_opaque_change:
        return []
    findings = []
    for file in ir.files:
        if file.role != "snapshot" or file.status != "modified":
            continue
        identity = change_identity(file)
        if identity['before_sha256'] == identity['after_sha256']:
            continue
        findings.append(Finding(
            rule="EXPECTED_VALUE_CHANGED",
            severity="warn",
            path=file.path,
            unit=None,
            message=("stored snapshot/golden expectation rewritten without an analysed "
                     "production implementation change; review the new expected content"),
            fingerprint=make_change_fingerprint(
                "EXPECTED_VALUE_CHANGED", file, {"event": "stored_expectation_rewritten"},
            ),
        ))
    return findings
