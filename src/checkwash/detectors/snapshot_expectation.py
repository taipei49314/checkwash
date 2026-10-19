"""The file-backed form of EXPECTED_VALUE_CHANGED (issue #129)."""
from collections import Counter

from checkwash.findings import Finding, change_identity, make_change_fingerprint
from checkwash.ir.model import DiffGlobals, IR


def _existing_prod_symbol_changed(g: DiffGlobals) -> bool:
    """Did a Python prod symbol change in a file the diff did not add (#463)?

    `prod_symbols_changed` holds an added file's symbols too, and
    `prod_symbols_in_added_files` names each of them once. The difference is
    a multiset one, not a set one: an added `pkg.py` and a modified
    `pkg/__init__.py` can both give `pkg::X`, and the modified one counts.
    """
    remaining = Counter(g.prod_symbols_changed)
    remaining.subtract(g.prod_symbols_in_added_files)
    return any(count > 0 for count in remaining.values())


def detect(ir: IR) -> list[Finding]:
    # Preserve the existing snapshot co-change policy, including its broad
    # treatment of unrelated or opaque production changes: a changed symbol
    # in any existing or deleted Python production file, whether or not a
    # test reaches it (ruling 463.Q2 (a)), and any opaque production change
    # (463.Q3 (a)). A Python production file the diff adds is not an
    # implementation change here (463.Q1 (a)): nothing in a brand-new file
    # explains rewriting an existing stored expectation, which is why
    # repair-evidence clause 3 and PACKAGE_REPAIR refuse new code too. The
    # cost, open for the owner (D-157): a pytest file kept under a snapshot
    # directory is a stored expectation too (#219), so a test added there for
    # a new module now reports this. A comment-only production edit does not
    # qualify either: it changes no symbol.
    if ir.globals.prod_opaque_change or _existing_prod_symbol_changed(ir.globals):
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
