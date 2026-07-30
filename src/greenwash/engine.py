"""Pipeline orchestration: FileChange list â†’ IR â†’ findings â†’ verdict.

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
    old_path: str | None = None  # set for git renames (R status)
    synthetic: str | None = None  # marks halves of an expanded rename


class EngineError(Exception):
    pass


def collectable(path: str) -> bool:
    """Would pytest's default collection (test_*.py / *_test.py) run this file?

    Role globs say what a path is *for*; collectability says whether its tests
    actually execute. A rename that keeps the test role but leaves collection
    (tests/billing_checks.py) kills the tests just as dead as deletion.
    """
    base = path.rsplit("/", 1)[-1]
    return (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py")


def _expand_renames(changes: list[FileChange], config: Config) -> list[FileChange]:
    """A rename that moves a test file out of collection is a disappearance.

    git's rename folding would otherwise analyse only the new path: `git mv
    tests/test_x.py attic/legacy.py` (R100) erased every unit from analysis
    with zero findings (confirmed red-team bypass). The added half is marked
    synthetic so relocated bytes don't count as a "non-trivial prod change"
    and defuse E1.
    """
    expanded: list[FileChange] = []
    for change in changes:
        old = (change.old_path or "").replace("\\", "/")
        new = change.path.replace("\\", "/")
        if old and old != new:
            old_test = config.role_of(old) == "test" and collectable(old)
            new_test = config.role_of(new) == "test" and collectable(new)
            if old_test and not new_test:
                expanded.append(FileChange(old, "deleted", change.before, None))
                expanded.append(
                    FileChange(new, "added", None, change.after, synthetic="renamed_from_test")
                )
                continue
        expanded.append(change)
    return expanded


# Deterministic markers of a weakened test command in CI files.
_CI_WEAKENING_TOKENS = (
    "continue-on-error",
    "|| true",
    "--ignore",
    " -k ",
    "--deselect",
    "--no-cov-fail",
)

# Invisible / direction-control characters (SPEC: HIDDEN_UNICODE).
_HIDDEN_CODEPOINTS = frozenset(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x00AD]
    + list(range(0x202A, 0x202F))
    + list(range(0x2066, 0x206A))
    + [0xFEFF]
)


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _added_lines(before: bytes | None, after: bytes | None) -> list[str]:
    b = Counter(_decode(before).split("\n"))
    lines = []
    for line in _decode(after).split("\n"):
        if b[line] > 0:
            b[line] -= 1
        else:
            lines.append(line)
    return lines


def _scan_hidden_unicode(g: DiffGlobals, path: str, before: bytes | None, after: bytes | None) -> None:
    if after is None or len(after) > 1_000_000:
        return
    for line in _added_lines(before, after):
        hit = next((ch for ch in line if ord(ch) in _HIDDEN_CODEPOINTS), None)
        if hit is not None:
            escaped = "".join(
                f"\\u{ord(c):04x}" if ord(c) in _HIDDEN_CODEPOINTS else c for c in line
            )
            g.hidden_unicode.append((path, f"U+{ord(hit):04X}", escaped.strip()[:200]))


def _scan_ci_weakening(g: DiffGlobals, path: str, before: bytes | None, after: bytes | None) -> None:
    for line in _added_lines(before, after):
        lowered = line.lower()
        if any(token in lowered for token in _CI_WEAKENING_TOKENS):
            g.ci_weakening_lines.append((path, line.strip()[:200]))


def _classify_allowlist_change(before: bytes | None, after: bytes | None) -> list[str] | None:
    """Fingerprints of appended entries if the change is append-only and
    schema-valid, else None (→ guardrail critical). SPEC §6 / DECISIONS D-003."""
    from greenwash.allowlist import load_allowlist

    before_entries, before_err = load_allowlist(before)
    after_entries, after_err = load_allowlist(after)
    if before_err or after_err:
        return None
    if after is None or len(after_entries) < len(before_entries):
        return None
    if after_entries[: len(before_entries)] != before_entries:
        return None
    return [e.fingerprint for e in after_entries[len(before_entries) :]]


def build_ir(
    changes: list[FileChange],
    config: Config,
    base_label: str,
    head_label: str,
    scope_allow: list[str] | None = None,
    known_modules: set[str] | None = None,
) -> IR:
    g = DiffGlobals()
    g.scope_allow = sorted(scope_allow or [])
    ir = IR(base=base_label, head=head_label, globals=g)
    removed_texts: Counter[str] = Counter()
    added_texts: Counter[str] = Counter()
    base_literals: set[str] = set()
    # Imports already present on the base side are presumed resolvable:
    # only NEW imports can be hallucinated.
    resolvable: set[str] | None = None
    if known_modules is not None:
        resolvable = set(known_modules)
        for change in changes:
            for part in change.path.replace("\\", "/").split("/"):
                resolvable.add(part[:-3] if part.endswith(".py") else part)

    for change in sorted(_expand_renames(changes, config), key=lambda c: c.path):
        path = change.path.replace("\\", "/")
        role = config.role_of(path)
        is_python = path.endswith(".py")

        before_parsed: ParsedFile | None = None
        after_parsed: ParsedFile | None = None
        if is_python:
            is_conftest = role == "conftest"
            collect = is_conftest or (role == "test" and collectable(path))
            if change.before is not None:
                before_parsed = parse_python(
                    change.before, collect_tests=collect, conftest=is_conftest
                )
            if change.after is not None:
                after_parsed = parse_python(
                    change.after, collect_tests=collect, conftest=is_conftest
                )

        file_ir = align_file(path, role, change.status, before_parsed, after_parsed)
        ir.files.append(file_ir)
        if is_python and not file_ir.parse_ok:
            ir.skipped_files.append(path)

        if role in ("test", "conftest"):
            for unit in file_ir.units:
                if unit.before is None or unit.after is None:
                    g.test_logic_changed = True
                elif unit.delta is not None and (
                    unit.delta.assertion_pairs
                    or unit.delta.assertions_removed
                    or unit.delta.assertions_added
                    or unit.delta.markers_added
                    or unit.delta.param_cases_removed
                ):
                    g.test_logic_changed = True

        if g.scope_allow and not any(
            _scope_match(path, glob) for glob in g.scope_allow
        ):
            g.scope_drift.append((path, role))

        if role in ("test", "conftest", "prod", "ci", "guardrail"):
            _scan_hidden_unicode(g, path, change.before, change.after)

        # Assertions landing in a disabled unit never run, so they cannot
        # count as "moved" â€” otherwise a sacrificial @pytest.mark.skip test
        # buys D2 de-escalation for real deletions (confirmed red-team
        # finding).
        for unit in file_ir.units:
            live_after = unit.after is not None and not unit.after.disabled
            if unit.delta is not None and unit.before is not None and unit.after is not None:
                b_by_id = {a.id: a for a in unit.before.assertions}
                a_by_id = {a.id: a for a in unit.after.assertions}
                for aid in unit.delta.assertions_removed:
                    if aid in b_by_id:
                        removed_texts[normalize_text(b_by_id[aid].text)] += 1
                if live_after:
                    for aid in unit.delta.assertions_added:
                        if aid in a_by_id:
                            added_texts[normalize_text(a_by_id[aid].text)] += 1
            elif unit.before is not None and unit.after is None:
                for a in unit.before.assertions:
                    removed_texts[normalize_text(a.text)] += 1
            elif unit.after is not None and unit.before is None:
                if live_after:
                    for a in unit.after.assertions:
                        added_texts[normalize_text(a.text)] += 1

        if change.synthetic == "renamed_from_test":
            # Relocated test bytes are not production behaviour change; they
            # must not defuse E1 nor feed prod symbol/literal/import globals.
            pass
        elif role == "prod":
            g.prod_files_changed.append(path)
            if is_python and before_parsed and after_parsed and before_parsed.parse_ok and after_parsed.parse_ok:
                syms = set(before_parsed.symbols) | set(after_parsed.symbols)
                for q in sorted(syms):
                    if before_parsed.symbols.get(q) != after_parsed.symbols.get(q):
                        g.prod_symbols_changed.append(q)
                _record_callers(g, after_parsed, g.prod_symbols_changed)
                g.new_literals_in_prod.extend(sorted(after_parsed.literals - before_parsed.literals))
            elif is_python and change.status == "added" and after_parsed and after_parsed.parse_ok:
                g.prod_symbols_changed.extend(sorted(after_parsed.symbols))
                _record_callers(g, after_parsed, g.prod_symbols_changed)
                g.new_literals_in_prod.extend(sorted(after_parsed.literals))
            else:
                # Non-Python prod file, deletion, or parse failure: greenwash
                # cannot tell repair from decoy here, so it conservatively
                # suppresses E1 (THREATMODEL.md #4).
                if (change.before or b"") != (change.after or b""):
                    g.prod_opaque_change = True
        elif role == "guardrail":
            if path == ".greenwash/allow.toml":
                appended = _classify_allowlist_change(change.before, change.after)
                if appended is not None:
                    g.exemptions_added.extend(appended)
                else:
                    g.guardrail_files_changed.append(path)
            else:
                g.guardrail_files_changed.append(path)
        elif role == "ci":
            g.ci_files_changed.append(path)
            _scan_ci_weakening(g, path, change.before, change.after)
        elif role == "snapshot":
            g.snapshot_files_changed.append(path)

        if is_python and before_parsed is not None and before_parsed.parse_ok:
            base_literals.update(before_parsed.literals)

        if is_python:
            before_sup = _suppression_texts(before_parsed)
            after_sup = _suppression_texts(after_parsed)
            for text, count in (after_sup - before_sup).items():
                g.suppressions_added.extend([f"{path}:{text}"] * count)
            if (
                before_parsed is not None
                and after_parsed is not None
                and before_parsed.parse_ok
                and after_parsed.parse_ok
            ):
                added_imports = sorted(set(after_parsed.imports) - set(before_parsed.imports))
            elif change.status == "added" and after_parsed is not None and after_parsed.parse_ok:
                added_imports = sorted(set(after_parsed.imports))
            else:
                added_imports = []
            for module in added_imports:
                g.imports_added.append(f"{path}:{module}")
                if resolvable is not None and module.split(".", 1)[0] not in resolvable:
                    g.unresolved_imports.append((path, module))
            before_broad = Counter((before_parsed.broad_handlers if before_parsed and before_parsed.parse_ok else ()))
            after_broad = Counter((after_parsed.broad_handlers if after_parsed and after_parsed.parse_ok else ()))
            for text, count in sorted((after_broad - before_broad).items()):
                g.broad_excepts_added.extend([(path, text)] * count)

    g.moved_assertion_texts = sorted(set(removed_texts) & set(added_texts))
    g.base_literals = sorted(base_literals)
    g.suppressions_added.sort()
    g.imports_added.sort()
    g.unresolved_imports.sort()
    g.broad_excepts_added.sort()
    g.ci_weakening_lines.sort()
    g.hidden_unicode.sort()
    g.scope_drift.sort()
    g.exemptions_added.sort()
    return ir


def _scope_match(path: str, pattern: str) -> bool:
    import fnmatch

    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
        return True
    return False


def _record_callers(g: DiffGlobals, parsed: ParsedFile, changed: list[str]) -> None:
    """Index which prod symbols call a changed symbol (one-hop repair evidence).

    A test that calls `format_invoice` is legitimately updated when
    `compute_total` â€” which format_invoice calls â€” changes; without this the
    symbol-level E1 would fire on that honest work.
    """
    changed_leaves = {q.rsplit(".", 1)[-1] for q in changed}
    for qual, callees in parsed.symbol_calls.items():
        hits = sorted(set(callees) & changed_leaves)
        if hits:
            g.prod_symbol_callers[qual.rsplit(".", 1)[-1]] = hits


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
    known_modules: set[str] | None = None,
) -> tuple[IR, list[Finding], str]:
    ir = build_ir(
        changes,
        config,
        base_label,
        head_label,
        scope_allow=contract.scope_allow,
        known_modules=known_modules,
    )
    findings = run_detectors(ir, config)
    verdict = apply_gates(ir, findings, contract, config, allow_entries, today)
    return ir, findings, verdict
