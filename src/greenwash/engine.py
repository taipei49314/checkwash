"""Pipeline orchestration: FileChange list → IR → findings → verdict.

Source-agnostic: gitio and the .gwcase runner both produce FileChange lists,
so fixtures exercise the exact same pipeline the CLI runs.

Role / CI / evidence helpers live in greenwash.roles, .ci, .evidence (E5).
"""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import replace

from greenwash.allowlist import AllowEntry
from greenwash.change import EngineError, FileChange
from greenwash.ci import (
    _ci_base_surface,
    _deps_differ,
    _is_ci_workflow,
    _runs_tests,
    _scan_ci_weakening,
)
from greenwash.config import Config
from greenwash.contract import Contract
from greenwash.deps import MANIFESTS
from greenwash.detectors import REGISTRY
from greenwash.evidence import (
    _MAX_DUP_READS,
    _gate_constants,
    _mark_weakened_guards,
    _module_of,
    _record_callers,
    _scope_match,
    _suppression_texts,
)
from greenwash.findings import Finding
from greenwash.frontends.python.frontend import (
    ParsedFile,
    conftest_patch_targets,
    parse_python,
)
from greenwash.gating import apply_gates, unit_is_live
from greenwash.ir.diffalign import align_file
from greenwash.ir.model import IR, DiffGlobals, normalize_text
from greenwash.pyenv import known_baseline
from greenwash.roles import (
    _MAX_ORACLE_READS,
    _added_lines,
    _is_inert,
    _is_runner_script,
    _mentions_test_runner,
    _one_hop_runners,
    collectable,
    is_artifact,
)

__all__ = [
    "EngineError",
    "FileChange",
    "analyze",
    "build_ir",
    "collectable",
    "is_artifact",
    "run_detectors",
    "_is_runner_script",
]


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
    self_modules: set[str] | None = None,
    head_reader=None,
    head_searcher=None,
) -> IR:
    g = DiffGlobals()
    g.scope_allow = sorted(scope_allow or [])
    # Someone else's code = declared, minus the project's own name, minus the
    # repo's own top-level directories. Without the subtractions this set
    # contains the package under test and the first-party check inverts.
    if known_modules is not None:
        repo_roots = {
            part[:-3] if part.endswith(".py") else part
            for change in changes
            for part in change.path.replace("\\", "/").split("/")
        }
        g.third_party_roots = tuple(
            sorted(set(known_modules) - set(self_modules or ()) - repo_roots - known_baseline())
        )
    ir = IR(base=base_label, head=head_label, globals=g)
    removed_texts: Counter[str] = Counter()
    added_texts: Counter[str] = Counter()
    base_literals: set[str] = set()
    # After-side parses, kept so skip-condition constants imported from
    # another file in the same diff resolve without re-reading anything.
    after_by_path: dict[str, ParsedFile] = {}
    before_by_path: dict[str, ParsedFile] = {}
    # Imports already present on the base side are presumed resolvable:
    # only NEW imports can be hallucinated.
    resolvable: set[str] | None = None
    if known_modules is not None:
        resolvable = set(known_modules)
        for change in changes:
            for part in change.path.replace("\\", "/").split("/"):
                resolvable.add(part[:-3] if part.endswith(".py") else part)

    # Computed once, before anything is judged: E6 needs to know what the
    # ci surface already said, not just what this diff added to it.
    one_hop = _one_hop_runners(changes, config, head_reader)
    ci_base = _ci_base_surface(changes, config, one_hop)

    # Cross-file oracle resolution (A5-x) parses helper files straight from
    # the change bytes, memoised — never from the loop's parse cache, so it
    # cannot depend on the order sorted() happens to visit paths in.
    raw_by_path: dict[str, tuple[bytes | None, bytes | None]] = {
        c.path.replace("\\", "/"): (c.before, c.after) for c in changes
    }
    oracle_memo: dict[tuple[str, int], ParsedFile | None] = {}
    oracle_head_reads = [0]

    def _oracle_file(opath: str, side: int) -> ParsedFile | None:
        """A test/conftest module parsed for its oracle carriers, or None.

        side 0 = base, 1 = head. A file outside the diff is identical on both
        sides, so the head snapshot serves base and head alike; a file *added*
        by the diff has no base half, which is what makes an extraction's
        before side resolve to nothing — correctly.
        """
        key = (opath, side)
        if key in oracle_memo:
            return oracle_memo[key]
        parsed: ParsedFile | None = None
        if opath in raw_by_path:
            data = raw_by_path[opath][side]
        elif head_reader is not None and oracle_head_reads[0] < _MAX_ORACLE_READS:
            oracle_head_reads[0] += 1
            data = head_reader(opath)
        else:
            data = None
        if data is not None and config.role_of(opath) in ("test", "conftest"):
            parsed = parse_python(
                data, collect_tests=True, conftest=opath.endswith("conftest.py")
            )
            if not parsed.parse_ok:
                parsed = None
        oracle_memo[key] = parsed
        return parsed

    def _merge_crossfile_oracles(tpath: str, parsed: ParsedFile, side: int) -> None:
        """Fold imported-helper and requested-fixture asserts into each unit.

        Two channels, both pre-registered in docs/defence-design.md A5-x:
        a unit-invoked name bound by a top-level `from M import f` whose module
        is a same-directory test/conftest sibling contributes f's own asserts;
        a fixture the unit requests by parameter name (same file or same-dir
        conftest) contributes everything lexically inside it. A fixture nobody
        requests contributes nothing — moving the oracle into one stays a
        removal. Each side resolves independently, so a helper added by the
        diff has no base half and an extraction's before side stays bare.

        Autouse fixtures from a head-only conftest are skipped on purpose:
        both sides would receive identical asserts, no rule could see a delta,
        and every unit in the file would grow oracle mass it did nothing to
        earn. An autouse fixture in a conftest *the diff touches* can differ
        between sides, so those are applied.
        """
        if parsed is None or not parsed.parse_ok or not parsed.units:
            return
        tdir = tpath.rsplit("/", 1)[0] if "/" in tpath else ""
        conftest_path = f"{tdir}/conftest.py" if tdir else "conftest.py"

        for unit in parsed.units:
            uside = unit.side
            extra = []
            requested = list(uside.params)
            conftest = None
            if requested and any(p not in parsed.fixture_asserts for p in requested):
                conftest = _oracle_file(conftest_path, side)
            for p in requested:
                found = parsed.fixture_asserts.get(p)
                if found is None and conftest is not None:
                    found = conftest.fixture_asserts.get(p)
                if found:
                    extra.extend(found)
            for name in parsed.autouse_fixtures:
                if name not in requested:
                    extra.extend(parsed.fixture_asserts.get(name, ()))
            if conftest_path in raw_by_path and conftest_path != tpath:
                c = _oracle_file(conftest_path, side)
                if c is not None:
                    for name in c.autouse_fixtures:
                        if name not in requested:
                            extra.extend(c.fixture_asserts.get(name, ()))
            for n in sorted(set(uside.invoked) & set(parsed.from_imports)):
                module, orig = parsed.from_imports[n]
                if "." in module:
                    candidate = module.replace(".", "/") + ".py"
                else:
                    candidate = f"{tdir}/{module}.py" if tdir else f"{module}.py"
                helper = _oracle_file(candidate, side)
                if helper is not None:
                    extra.extend(helper.helper_asserts.get(orig, ()))
            if extra:
                uside.assertions.extend(replace(a) for a in extra)
                for i, a in enumerate(uside.assertions):
                    a.id = f"a{i}"

    for change in sorted(_expand_renames(changes, config), key=lambda c: c.path):
        path = change.path.replace("\\", "/")
        if is_artifact(path):
            continue  # generated output is not evidence of anything
        role = config.role_of(path)
        if role == "prod" and (
            _is_runner_script(path, change.before, change.after) or path in one_hop
        ):
            # The test command lives wherever the project keeps it. As prod
            # this file was unreadable, which meant editing it both hid a
            # weakened command *and* granted the whole diff the THREATMODEL #4
            # opaque exemption — one line of `scripts/test.sh` turned a
            # blocking assertion weakening into a warn (probe 2026-08-07).
            role = "ci"
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

        if after_parsed is not None and after_parsed.parse_ok:
            after_by_path[path] = after_parsed
        if before_parsed is not None and before_parsed.parse_ok:
            before_by_path[path] = before_parsed

        if is_python and role == "test" and collect:
            if before_parsed is not None:
                _merge_crossfile_oracles(path, before_parsed, 0)
            if after_parsed is not None:
                _merge_crossfile_oracles(path, after_parsed, 1)

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
        elif (
            role in ("test", "conftest")
            and after_parsed is None
            and before_parsed
            and before_parsed.parse_ok
        ):
            # A deleted test file's units are judged against what that file
            # imported when it existed — without this, PROD_SYMBOL_REMOVED
            # could never connect a deleted test file to the feature removal
            # that explains it (starlette b133ab45ad deletes both halves).
            g.test_file_imports[path] = list(before_parsed.imports)
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

        if path in MANIFESTS and _deps_differ(change.before, change.after):
            g.dependency_manifest_changed = True

        if role == "conftest" and change.after is not None:
            first_party = frozenset(
                p.replace("\\", "/").split("/")[0].removesuffix(".py")
                for p in (c.path for c in changes)
            ) | frozenset(
                _module_of(f.path).split(".")[0] for f in ir.files if f.role == "prod"
            )
            before_patches = (
                set(conftest_patch_targets(change.before, first_party))
                if change.before is not None
                else set()
            )
            for text in conftest_patch_targets(change.after, first_party):
                if text not in before_patches:
                    g.conftest_prod_patches.append((path, text))

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
                        # A deletion counts as feature removal only when its
                        # enclosing scope is gone too. Symbol collection
                        # records assignments inside functions, so a rewritten
                        # function "deletes" its old locals — and that let a
                        # body rewrite escort a test deletion into the D8
                        # credit (click b7e5fd4cc7, adjudicated spec-correct,
                        # cleared by the first cut of this rule). A surviving
                        # prefix means internal rewrite, not removal.
                        if q in before_parsed.symbols and q not in after_parsed.symbols:
                            parts = q.split(".")
                            prefixes = (".".join(parts[:i]) for i in range(1, len(parts)))
                            if not any(p in after_parsed.symbols for p in prefixes):
                                g.prod_symbols_deleted.append(f"{_module_of(path)}::{q}")
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
            elif (
                is_python
                and change.status == "deleted"
                and before_parsed is not None
                and before_parsed.parse_ok
            ):
                # A deleted Python file is fully analysable from its base
                # side: every symbol in it changed, and every one is gone.
                # It used to fall into the opaque blanket, which handed a
                # diff-wide exemption to five corpus commits whose deletion
                # was perfectly readable. Symbol-level evidence and D8 now
                # judge it like any other change.
                for q in sorted(before_parsed.symbols):
                    g.prod_symbols_changed.append(f"{_module_of(path)}::{q}")
                    g.prod_symbols_deleted.append(f"{_module_of(path)}::{q}")
            elif is_artifact(path):
                # Generated output: no evidence either way, and crediting it
                # would let any build artifact disarm the gate.
                pass
            elif _is_inert(path):
                # Docs config, stubs, repo metadata: changes no runtime
                # behaviour, so it is neither evidence nor opaque.
                pass
            else:
                # Other-language code, templates, data files, or a Python
                # parse failure: greenwash cannot tell repair from decoy
                # here, so it conservatively suppresses E1 (THREATMODEL #4).
                #
                # But it must be a *change to something that was already
                # production*. Told to defeat this tool and handed its source,
                # an agent read this branch and wrote a three-line
                # `retry_policy.json` that nothing imports, purely to be
                # unreadable, and both rewritten expectations passed
                # (informed arm 2026-08-07). A file that did not exist before
                # cannot be the repair of behaviour that did — and if a new
                # file genuinely implements a fix, the Python that reaches it
                # changed too and supplies the evidence itself.
                # v0.1.10 spelled that as "was there a byte on the base
                # side", which is weaker than the argument in three ways an
                # audit then reproduced (rows 78-80). The exemption needs a
                # *modification of something that was already production*:
                #
                #  - not a deletion. `git rm` of an unread data file bought
                #    the exemption for a whole diff, and row 73's own
                #    reasoning applies to removals word for word.
                #  - the base-side path must have been production too. Rename
                #    folding keeps the old blob as `before` while the role
                #    comes from the new path, so `docs/rules.md` renamed to
                #    `app/rules.csv` counted as pre-existing production the
                #    diff had in fact just invented.
                #  - not opacity this diff created. A prod `.py` that parsed
                #    at base and does not parse at head is reported as
                #    `skipped (unparseable)` in the same report; rewarding it
                #    is rewarding the agent for breaking the reader.
                #
                # The cost of all three is bounded and known: re-sweeping the
                # 1800-commit corpus with this exemption disabled *entirely*
                # moved the block set by zero commits in all six repositories,
                # so no subset of it can cost more than nothing here.
                old_path = (change.old_path or path).replace("\\", "/")
                self_inflicted = (
                    is_python
                    and before_parsed is not None
                    and before_parsed.parse_ok
                    and (after_parsed is None or not after_parsed.parse_ok)
                )
                if (
                    change.before
                    and change.after
                    and change.before != change.after
                    and config.role_of(old_path) == "prod"
                    and not self_inflicted
                    # 4. A file that runs the test suite is not unreadable
                    #    production code, whatever it is called. Without this,
                    #    an unrecognised runner filename was strictly better
                    #    for an attacker than a recognised one: it hid its own
                    #    weakening *and* disarmed every oracle rule in the diff
                    #    (THREATMODEL 87, measured 2026-08-11).
                    and not _mentions_test_runner(change)
                ):
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
            if not change.before:
                g.guardrail_files_created.append(path)
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
            _scan_ci_weakening(g, path, change.before, change.after, ci_base)
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

    # D6 constant environments, resolved here so gating stays a pure function
    # of the IR: same-file constants first, then names imported from files in
    # this diff, then from the head snapshot (click's `from click._compat
    # import WIN`, where _compat.py is not in the diff at all — FP sweep).
    for file in ir.files:
        parsed = after_by_path.get(file.path)
        if file.role in ("test", "conftest") and parsed is not None:
            file.constants = _gate_constants(parsed, after_by_path, head_reader)
            file.fixture_defs = dict(parsed.fixture_defs)
            before = before_by_path.get(file.path)
            if before is not None:
                file.constants_before = _gate_constants(before, before_by_path, None)
                file.fixture_defs_before = dict(before.fixture_defs)
                _mark_weakened_guards(file)

    # Move credits, counted after the constant environments exist because
    # liveness now consults them. Assertions (and whole units) landing in a
    # unit that does not run never count as "moved" — a sacrificial
    # @pytest.mark.skip test must not buy D2 de-escalation for real deletions
    # (confirmed red-team finding) — but a unit carried across files together
    # with its own compat gate is not dead, it is relocated (FP sweep, click
    # a391797d00 / 700798252a).
    removed_units: Counter[str] = Counter()
    added_units: Counter[str] = Counter()
    for file in ir.files:
        constants = file.constants
        for unit in file.units:
            live_after = unit.after is not None and unit_is_live(unit.after, constants)
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
                if unit.before.body_hash:
                    removed_units[unit.before.body_hash] += 1
            elif unit.after is not None and unit.before is None:
                if live_after:
                    for a in unit.after.assertions:
                        added_texts[normalize_text(a.text)] += 1
                    if unit.after.body_hash:
                        added_units[unit.after.body_hash] += 1

    # Multiset, not set (SPEC §7): deleting the same assertion from two tests
    # while adding one copy elsewhere must leave one deletion unexplained.
    # `set(a) & set(b)` credited both (confirmed bypass). Only as many
    # removals as there are additions may be called "moved". Units spend the
    # same way through their body hashes.
    moved = removed_texts & added_texts  # Counter intersection = min of counts
    g.moved_assertion_texts = sorted(moved.elements())
    g.moved_unit_hashes = sorted((removed_units & added_units).elements())

    # Duplicate survivors: a disappeared unit whose identical live body still
    # exists at head in a file this diff never touched. The needle search is
    # one batched call (git grep in range mode); only matching files are read
    # and parsed, capped. Deleting one of two identical copies leaves the
    # oracle running — the attack shapes (survivor skipped, survivor edited)
    # fail the liveness and hash checks and earn nothing.
    if head_searcher is not None and head_reader is not None:
        wanted: set[str] = set()
        needles: set[str] = set()
        for file in ir.files:
            if file.role not in ("test", "conftest"):
                continue
            for unit in file.units:
                if unit.before is not None and unit.after is None and unit.before.body_hash:
                    h = unit.before.body_hash
                    if added_units.get(h):
                        continue  # relocated within the diff; D2 covers it
                    wanted.add(h)
                    leaf = unit.qualname.rsplit(".", 1)[-1].split("#", 1)[0]
                    needles.add(f"def {leaf}(")
        if wanted:
            diff_paths = {f.path for f in ir.files}
            candidates = sorted(
                p.replace("\\", "/")
                for p in head_searcher(sorted(needles))
                if p.replace("\\", "/") not in diff_paths
                and p.endswith(".py")
                and config.role_of(p.replace("\\", "/")) == "test"
                and collectable(p.replace("\\", "/"))
            )
            found: set[str] = set()
            for path in candidates[:_MAX_DUP_READS]:
                data = head_reader(path)
                if data is None:
                    continue
                parsed = parse_python(data, collect_tests=True)
                if not parsed.parse_ok:
                    continue
                consts = _gate_constants(parsed, after_by_path, head_reader)
                for pu in parsed.units:
                    if pu.side.body_hash in wanted and unit_is_live(pu.side, consts):
                        found.add(pu.side.body_hash)
            g.duplicate_unit_hashes = sorted(found)
    return ir


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
    self_modules: set[str] | None = None,
    head_reader=None,
    head_searcher=None,
) -> tuple[IR, list[Finding], str]:
    ir = build_ir(
        changes,
        config,
        base_label,
        head_label,
        scope_allow=contract.scope_allow,
        known_modules=known_modules,
        self_modules=self_modules,
        head_reader=head_reader,
        head_searcher=head_searcher,
    )
    findings = run_detectors(ir, config)
    verdict = apply_gates(ir, findings, contract, config, allow_entries, today)
    return ir, findings, verdict
