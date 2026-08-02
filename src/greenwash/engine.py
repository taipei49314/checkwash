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


# Generated/binary artifacts. A changed file here says nothing about
# production behaviour, so it must never buy repair evidence: pytest's own
# untracked __pycache__/*.pyc silently disarmed the whole escalator in the
# first decoy run (0/12 caught), which any build artifact would reproduce.
_ARTIFACT_SEGMENTS = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "htmlcov",
        ".eggs",
    }
)
_ARTIFACT_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".a",
    ".o",
    ".class",
    ".jar",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".mo",
    ".coverage",
    ".log",
)


def is_artifact(path: str) -> bool:
    # Segment-anchored, not substring: `build/` used to match `mybuild/` and
    # `dist/` matched `redist/`, silently deleting real source trees from the
    # analysis — which is both a false negative and a one-rename bypass.
    p = path.replace("\\", "/")
    segments = p.split("/")
    if any(seg in _ARTIFACT_SEGMENTS or seg.endswith(".egg-info") for seg in segments):
        return True
    return segments[-1].lower().endswith(_ARTIFACT_SUFFIXES)


def collectable(path: str) -> bool:
    """Would pytest's default collection run this file?

    Role globs say what a path is *for*; collectability says whether its tests
    actually execute. A rename that keeps the test role but leaves collection
    (tests/billing_checks.py) kills the tests just as dead as deletion.

    Two rules, not one. pytest's filename patterns (`test_*.py`, `*_test.py`)
    decide the basename, and `norecursedirs` decides the directory: dot-dirs,
    build output and virtualenvs are never descended into. Judging the
    basename alone meant `git mv tests/test_x.py build/test_x.py` and
    `... .attic/test_x.py` both read as "still a collected test file", so the
    tests vanished from the suite and from the report (reader audit
    2026-08-02).
    """
    p = path.replace("\\", "/")
    segments = p.split("/")
    for seg in segments[:-1]:
        if seg in _ARTIFACT_SEGMENTS or seg.endswith(".egg-info"):
            return False
        if len(seg) > 1 and seg.startswith("."):
            return False  # pytest's default norecursedirs excludes `.*`
    base = segments[-1]
    return (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py")


# Roles whose files are supervised for their own sake. Moving a file out of
# one of these is itself the event, not a neutral relocation.
_SUPERVISED_ROLES = frozenset({"guardrail", "ci", "test", "conftest", "snapshot"})


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
            old_role = config.role_of(old)
            new_role = config.role_of(new)
            old_test = old_role == "test" and collectable(old)
            new_test = new_role == "test" and collectable(new)
            # Moving a file out of a supervised role is a way of escaping
            # supervision: `git mv AGENTS.md docs/AGENTS.old` or a workflow
            # out of .github/workflows/ silenced the guardrail and CI rules
            # entirely. Any such rename is expanded so the old path is still
            # judged under the role it had.
            escaped = old_role in _SUPERVISED_ROLES and new_role != old_role
            if (old_test and not new_test) or escaped:
                expanded.append(FileChange(old, "deleted", change.before, None))
                expanded.append(
                    FileChange(new, "added", None, change.after, synthetic="renamed_from_test")
                )
                continue
        expanded.append(change)
    return expanded


# Deterministic markers of a weakened test command in CI files.
# Anchored, not bare substrings: `--ignore` matched `--ignore-missing-imports`
# in a mypy step and blocked innocent CI edits at high.
# Enough of a test runner to call a workflow's removal a loss of coverage.
_TEST_RUNNER_TOKENS = (
    "pytest",
    "unittest",
    "tox",
    "nox",
    "npm test",
    "yarn test",
    "pnpm test",
    "go test",
    "cargo test",
    "make test",
    "gradle test",
    "mvn test",
    "dotnet test",
    "rspec",
    "jest",
    "vitest",
)

_CI_WEAKENING_TOKENS = (
    "continue-on-error: true",
    "|| true",
    "--ignore=",
    "--ignore ",
    "--deselect",
    ' -k "',
    " -k '",
    # pytest's own collection knobs. Narrowing `python_files` or `testpaths`,
    # or adding `-p no:...`, silences tests without touching a single test
    # file — and pytest.ini/tox.ini/setup.cfg/pyproject.toml had no role, so
    # nothing inspected them (reader audit 2026-08-02).
    "python_files",
    "python_classes",
    "python_functions",
    "testpaths",
    "norecursedirs",
    "collect_ignore",
    "-p no:",
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
    # Source files only. Data fixtures legitimately contain bidi/zero-width
    # characters (URL-parser test vectors), and binary blobs decode into
    # garbage that matches by accident — both confirmed on the FP sweep.
    if not path.endswith(".py"):
        return
    if after is None or len(after) > 1_000_000 or b"\x00" in after:
        return
    for line in _added_lines(before, after):
        hit = next((ch for ch in line if ord(ch) in _HIDDEN_CODEPOINTS), None)
        if hit is not None:
            escaped = "".join(
                f"\\u{ord(c):04x}" if ord(c) in _HIDDEN_CODEPOINTS else c for c in line
            )
            g.hidden_unicode.append((path, f"U+{ord(hit):04X}", escaped.strip()[:200]))


def _is_ci_workflow(path: str) -> bool:
    """A CI pipeline definition, as opposed to test-runner configuration.

    Deleting a workflow removes a gate. Deleting `tox.ini` or `setup.cfg`
    almost always means the settings moved into `pyproject.toml`, which is
    housekeeping — treating that as "the test command was weakened" blocked
    two such consolidations in the corpus. The edit is still reported at warn.
    """
    p = path.replace("\\", "/")
    return p.startswith(".github/workflows/") or p in (".gitlab-ci.yml", ".pre-commit-config.yaml")


def _runs_tests(data: bytes | None) -> bool:
    """Did this CI file actually run a test suite?

    Deliberately generous: any recognised runner anywhere in the file counts,
    because the cost of guessing wrong in this direction is one warn-level
    finding, while guessing wrong the other way blocks an honest commit.
    """
    if not data:
        return False
    text = data.decode("utf-8", errors="replace").lower()
    return any(token in text for token in _TEST_RUNNER_TOKENS)


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
        if is_artifact(path):
            continue  # generated output is not evidence of anything
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
            # A test file greenwash cannot parse is a test file greenwash did
            # not check. Reporting it only in `skipped_files` made the verdict
            # depend on the analysing interpreter's grammar: source using
            # newer-than-analyzer syntax was silently dropped and the run
            # passed, while the same diff blocked on a newer Python (reader
            # audit 2026-08-02). Now it is a finding, and one that escalates
            # when the file used to parse.
            if role in ("test", "conftest") and change.status != "deleted":
                was_parseable = before_parsed is not None and before_parsed.parse_ok
                g.unparseable_tests.append((path, was_parseable))

        if role in ("test", "conftest") and after_parsed and after_parsed.parse_ok:
            g.test_file_imports[path] = list(after_parsed.imports)
        if role in ("test", "conftest"):
            for unit in file_ir.units:
                if unit.before is None or unit.after is None:
                    g.test_logic_changed = True
                elif unit.delta is not None:
                    # `assertion_pairs` holds every matched pair, changed or
                    # not, so testing it for emptiness marked a comment-only
                    # edit as a logic change and silently switched off
                    # SNAPSHOT_CODE_COCHANGE (reader audit 2026-08-02). Only
                    # pairs whose text actually differs count.
                    b_by_id = {a.id: a for a in unit.before.assertions}
                    a_by_id = {a.id: a for a in unit.after.assertions}
                    edited = any(
                        (b := b_by_id.get(p.before_id)) is not None
                        and (a := a_by_id.get(p.after_id)) is not None
                        and normalize_text(b.text) != normalize_text(a.text)
                        for p in unit.delta.assertion_pairs
                    )
                    if edited or (
                        unit.delta.assertions_removed
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
            package = _module_of(path)
            if is_python and before_parsed and after_parsed and before_parsed.parse_ok and after_parsed.parse_ok:
                for q in sorted(set(before_parsed.symbols) | set(after_parsed.symbols)):
                    if before_parsed.symbols.get(q) != after_parsed.symbols.get(q):
                        g.prod_symbols_changed.append(f"{_module_of(path)}::{q}")
                        # PACKAGE_REPAIR credit requires a MODIFIED existing
                        # symbol in the package — a real behaviour change. A
                        # newly added dead function or a comment does not
                        # count, or it reopens bypass #4 for
                        # EXPECTED_VALUE_CHANGED (confirmed red-team finding).
                        if q in before_parsed.symbols and q in after_parsed.symbols:
                            g.prod_packages.append(package)
                _record_callers(g, after_parsed, g.prod_symbols_changed)
                g.new_literals_in_prod.extend(sorted(after_parsed.literals - before_parsed.literals))
            elif is_python and change.status == "added" and after_parsed and after_parsed.parse_ok:
                # A brand-new prod file is all new symbols; nothing "modified"
                # in it explains editing an existing test's expectation.
                g.prod_symbols_changed.extend(
                    f"{_module_of(path)}::{q}" for q in sorted(after_parsed.symbols)
                )
                _record_callers(g, after_parsed, g.prod_symbols_changed)
                g.new_literals_in_prod.extend(sorted(after_parsed.literals))
            elif is_artifact(path):
                # Generated output: no evidence either way, and crediting it
                # would let any build artifact disarm the gate.
                pass
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
            if change.status == "deleted" and _is_ci_workflow(path) and _runs_tests(change.before):
                # Deleting or relocating a workflow removes the gate outright,
                # which is at least as strong a signal as weakening a command
                # inside it — but only if that workflow ran the tests. Firing
                # on any removal blocked commits that dropped a lint-only
                # workflow (reader audit 2026-08-02, attrs 20734d9 dropping
                # pinact.yml). A removed non-test workflow still surfaces as
                # CI_WORKFLOW_TOUCHED at warn: visible, not blocking.
                g.ci_weakening_lines.append((path, "workflow file removed"))
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
            # A test file is judged on handlers that actually swallow an
            # oracle; production code on every broad handler added, because
            # there the cheat is silencing the error instead of fixing it.
            def _handlers(parsed: ParsedFile | None) -> tuple[str, ...]:
                if parsed is None or not parsed.parse_ok:
                    return ()
                if role in ("test", "conftest"):
                    return parsed.swallowing_handlers
                return parsed.broad_handlers

            before_broad = Counter(_handlers(before_parsed))
            after_broad = Counter(_handlers(after_parsed))
            for text, count in sorted((after_broad - before_broad).items()):
                g.broad_excepts_added.extend([(path, text)] * count)

    # Multiset, not set (SPEC §7): deleting the same assertion from two tests
    # while adding one copy elsewhere must leave one deletion unexplained.
    # `set(a) & set(b)` credited both (confirmed bypass). Only as many
    # removals as there are additions may be called "moved".
    moved = removed_texts & added_texts  # Counter intersection = min of counts
    g.moved_assertion_texts = sorted(moved.elements())
    g.base_literals = sorted(base_literals)
    # packages with >=1 genuinely modified symbol; deliberately NOT every
    # package with any prod change (see PACKAGE_REPAIR credit above).
    g.prod_packages = sorted(set(g.prod_packages))
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

    if fnmatch.fnmatchcase(path, pattern):  # case-folding fnmatch breaks §8
        return True
    if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
        return True
    return False


def _module_of(path: str) -> str:
    """`pkg/mod.py` -> `pkg.mod`. Symbols are qualified by module so a
    same-named function in an unrelated module cannot supply evidence.

    A leading `src/` is dropped. Under the src-layout that attrs, click and
    flask all use, `src/attr/_make.py` is imported as `attr._make`; keeping
    the source root in the name made the changed module unreachable from
    every test's imports, which silently denied repair evidence to every
    src-layout project in the corpus (reader audit 2026-08-02). Other source
    roots are handled by suffix alignment in gating._module_reachable.
    """
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    if p.startswith("src/"):
        p = p[len("src/") :]
    return p.replace("/", ".")


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
