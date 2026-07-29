"""Pipeline orchestration: FileChange list → IR → findings → verdict.

Source-agnostic: gitio and the .gwcase runner both produce FileChange lists,
so fixtures exercise the exact same pipeline the CLI runs.
"""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass

from greenwash.allowlist import AllowEntry
from greenwash.config import Config
from greenwash.contract import Contract
from greenwash.detectors import REGISTRY
from greenwash.findings import Finding
from greenwash.gating import apply_gates
from greenwash.ir.diffalign import align_file
from greenwash.ir.model import IR, DiffGlobals, normalize_text
from greenwash.frontends.python.frontend import ParsedFile, parse_python


@dataclass
class FileChange:
    path: str  # forward-slash normalized
    status: str  # added | modified | deleted
    before: bytes | None
    after: bytes | None


class EngineError(Exception):
    pass


def build_ir(changes: list[FileChange], config: Config, base_label: str, head_label: str) -> IR:
    g = DiffGlobals()
    ir = IR(base=base_label, head=head_label, globals=g)
    removed_texts: Counter[str] = Counter()
    added_texts: Counter[str] = Counter()

    for change in sorted(changes, key=lambda c: c.path):
        path = change.path.replace("\\", "/")
        role = config.role_of(path)
        is_python = path.endswith(".py")

        before_parsed: ParsedFile | None = None
        after_parsed: ParsedFile | None = None
        if is_python:
            collect = role == "test"
            if change.before is not None:
                before_parsed = parse_python(change.before, collect_tests=collect)
            if change.after is not None:
                after_parsed = parse_python(change.after, collect_tests=collect)

        file_ir = align_file(path, role, change.status, before_parsed, after_parsed)
        ir.files.append(file_ir)
        if is_python and not file_ir.parse_ok:
            ir.skipped_files.append(path)

        for unit in file_ir.units:
            if unit.delta is not None and unit.before is not None and unit.after is not None:
                b_by_id = {a.id: a for a in unit.before.assertions}
                a_by_id = {a.id: a for a in unit.after.assertions}
                for aid in unit.delta.assertions_removed:
                    if aid in b_by_id:
                        removed_texts[normalize_text(b_by_id[aid].text)] += 1
                for aid in unit.delta.assertions_added:
                    if aid in a_by_id:
                        added_texts[normalize_text(a_by_id[aid].text)] += 1
            elif unit.before is not None and unit.after is None:
                for a in unit.before.assertions:
                    removed_texts[normalize_text(a.text)] += 1
            elif unit.after is not None and unit.before is None:
                for a in unit.after.assertions:
                    added_texts[normalize_text(a.text)] += 1

        if role == "prod":
            g.prod_files_changed.append(path)
            if is_python and before_parsed and after_parsed and before_parsed.parse_ok and after_parsed.parse_ok:
                syms = set(before_parsed.symbols) | set(after_parsed.symbols)
                for q in sorted(syms):
                    if before_parsed.symbols.get(q) != after_parsed.symbols.get(q):
                        g.prod_symbols_changed.append(q)
                if before_parsed.module_fingerprint != after_parsed.module_fingerprint:
                    g.prod_nontrivial_change = True
                g.new_literals_in_prod.extend(sorted(after_parsed.literals - before_parsed.literals))
                g.imports_added.extend(sorted(set(after_parsed.imports) - set(before_parsed.imports)))
            elif is_python and change.status == "added" and after_parsed and after_parsed.parse_ok:
                g.prod_nontrivial_change = True
                g.prod_symbols_changed.extend(sorted(after_parsed.symbols))
                g.new_literals_in_prod.extend(sorted(after_parsed.literals))
                g.imports_added.extend(sorted(set(after_parsed.imports)))
            else:
                # Non-Python prod file, deletion, or parse failure: any textual
                # difference conservatively counts as a non-trivial change
                # (suppresses E1; documented in THREATMODEL.md #2).
                if (change.before or b"") != (change.after or b""):
                    g.prod_nontrivial_change = True
        elif role == "guardrail":
            g.guardrail_files_changed.append(path)
        elif role == "ci":
            g.ci_files_changed.append(path)
        elif role == "snapshot":
            g.snapshot_files_changed.append(path)

        if is_python:
            before_sup = _suppression_texts(before_parsed)
            after_sup = _suppression_texts(after_parsed)
            for text, count in (after_sup - before_sup).items():
                g.suppressions_added.extend([f"{path}:{text}"] * count)

    g.moved_assertion_texts = sorted(set(removed_texts) & set(added_texts))
    g.suppressions_added.sort()
    return ir


def _suppression_texts(parsed: ParsedFile | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if parsed is None:
        return counter
    for entry in parsed.suppressions:
        counter[entry.split(":", 1)[1] if ":" in entry else entry] += 1
    return counter


def run_detectors(ir: IR, config: Config) -> list[Finding]:
    findings: list[Finding] = []
    for rule, detect in REGISTRY.items():
        if rule in config.disabled_detectors:
            continue
        findings.extend(detect(ir))
    findings.sort(key=lambda f: f.sort_key())
    return findings


def analyze(
    changes: list[FileChange],
    config: Config,
    contract: Contract,
    allow_entries: list[AllowEntry],
    today: datetime.date,
    base_label: str = "base",
    head_label: str = "head",
) -> tuple[IR, list[Finding], str]:
    ir = build_ir(changes, config, base_label, head_label)
    findings = run_detectors(ir, config)
    verdict = apply_gates(ir, findings, contract, config, allow_entries, today)
    return ir, findings, verdict
