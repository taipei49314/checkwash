"""Pipeline orchestration: FileChange list → IR → findings → verdict.

Source-agnostic: gitio and the .gwcase runner both produce FileChange lists,
so fixtures exercise the exact same pipeline the CLI runs.

Role / CI / evidence helpers live in checkwash.roles, .ci, .evidence (E5).
"""

from __future__ import annotations

import ast
import copy
import datetime
import keyword
from collections import Counter
from dataclasses import dataclass, replace

from checkwash.allowlist import AllowEntry
from checkwash.change import EngineError, FileChange
from checkwash.ci import (
    _ci_base_surface,
    _deps_differ,
    _is_ci_workflow,
    _runs_tests,
    _scan_ci_weakening,
)
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.deps import MANIFESTS
from checkwash.detectors import REGISTRY
from checkwash.evidence import (
    _MAX_DUP_READS,
    _gate_constants,
    _mark_weakened_guards,
    _module_of,
    _record_callers,
    _scope_match,
    _suppression_texts,
)
from checkwash.findings import Finding
from checkwash.frontends.javascript.frontend import is_js_test_path, parse_javascript
from checkwash.frontends.python.frontend import (
    ParsedFile,
    _definition_import_maps,
    _fixture_is_autouse,
    _fixture_public_name,
    _module_callable_scopes,
    _required_injected_parameters,
    conftest_patch_targets,
    parse_python,
)
from checkwash.gating import apply_gates, unit_is_live
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import IR, DiffGlobals, normalize_text
from checkwash.pyenv import known_baseline
from checkwash.roles import (
    _MAX_ORACLE_READS,
    _added_lines,
    _is_inert,
    _is_runner_script,
    _mentions_test_runner,
    _one_hop_runners,
    collectable,
    is_artifact,
)
from checkwash.standins import (
    StandinInstall,
    _provider_context,
    install_applies,
    install_reaches,
    new_reaching_effects,
    new_unit_standin_installs,
    target_is_repo_owned,
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
_NON_HISTORIC_EARLY_CONFTEST_HOOKS = frozenset({"pytest_sessionstart"})
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


@dataclass(frozen=True)
class _FixtureProvider:
    provider_id: str
    public_name: str
    dependencies: tuple[str, ...]
    autouse: bool
    start_line: int
    end_line: int
    transparent_receiver: str | None = None


@dataclass(frozen=True)
class _FixtureResolution:
    active: frozenset[tuple[str, str]]
    trusted_receivers: frozenset[tuple[str, str]]
    provider_order: tuple[tuple[str, str], ...]


def _initial_conftest_for_default_collection(path: str) -> bool:
    """Whether default root collection loads this conftest before sessionstart.

    Pytest initially loads the invocation-root conftest and immediate ``test*``
    directories. Other directory conftests arrive during traversal, after the
    non-historic session-start hook has fired. Explicit CLI paths/testpaths can
    broaden that initial set, but the engine has no runner-path input and must
    not claim a definite early effect from that conditional environment.
    """
    path = path.replace("\\", "/")
    if path == "conftest.py":
        return True
    if path.count("/") != 1:
        return False
    return path.split("/", 1)[0].casefold().startswith("test")


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

_OWN_CONFIG_PATHS = (".checkwash/config.toml", ".greenwash/config.toml")


def _created_config_loosens(after: bytes | None) -> bool:
    """A checkwash config that did not exist was the defaults. A new one that
    disables a detector or raises `fail_on` above the default relaxes them:
    the two-commit plant of issue #79 (create the config at warn, weaken the
    test on the next diff under the disabled rule). Such a creation is E4 like
    any modification. A file that only tightens, or only comments, is not; an
    unparseable one is not either — the defaults stay in force and the parse
    error surfaces on the next diff. `roles` overrides are a stated residual:
    a monorepo's first role table cannot be told from a narrowing one."""
    from checkwash.config import SEVERITY_ORDER, load_config

    cfg, err, _warnings = load_config(after)
    if err:
        return False
    if cfg.disabled_detectors:
        return True
    return SEVERITY_ORDER[cfg.fail_on] > SEVERITY_ORDER["high"]


def _classify_allowlist_change(before: bytes | None, after: bytes | None) -> list[str] | None:
    """Fingerprints of appended entries if the change is append-only and
    schema-valid, else None (→ guardrail critical). SPEC §6 / DECISIONS D-003."""
    from checkwash.allowlist import load_allowlist

    before_entries, before_err = load_allowlist(before)
    after_entries, after_err = load_allowlist(after)
    if before_err or after_err:
        return None
    if after is None or len(after_entries) < len(before_entries):
        return None
    if after_entries[: len(before_entries)] != before_entries:
        return None
    return [e.fingerprint for e in after_entries[len(before_entries) :]]


def _canonical_constants(raw: dict[str, str]) -> dict[str, str]:
    """Top-level constant name -> canonical defining expression.

    `_top_level_constants` records raw source segments — right for D6, which
    resolves and evaluates them, wrong for a two-sided comparison, where a
    reformat would read as a change (the binding channel's first false
    positive, solved there with `ast.unparse`; same medicine here). A segment
    that does not parse as an expression is skipped: the arm goes silent on
    it rather than comparing bytes it cannot normalize.
    """
    out: dict[str, str] = {}
    for name, seg in raw.items():
        try:
            out[name] = ast.unparse(ast.parse(seg, mode="eval"))
        except (SyntaxError, ValueError):
            continue
    return out


def _safe_repo_path(path: str) -> str | None:
    """Normalize a safe repository-relative path, or reject it.

    Head callbacks eventually address repository storage.  Neither a search
    result nor a string-built stand-in target may turn them into an ambient
    filesystem read on Windows or POSIX.
    """
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return None
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    if any(
        part != part.rstrip(" .")
        or part.split(".", 1)[0].casefold() in _WINDOWS_DEVICE_NAMES
        for part in parts
    ):
        # Win32 normalizes trailing dots/spaces and treats these basenames as
        # ambient devices even when an extension is present (``NUL.py``).
        return None
    return "/".join(parts)


def _standin_module_paths(install: StandinInstall) -> tuple[str, ...]:
    """Safe conventional ownership paths, longest module prefix first."""
    target = install.target
    if target.startswith((".", "request.module")):
        return ()
    pieces = target.split(".")
    if not pieces or not all(
        piece.isidentifier() and not keyword.iskeyword(piece)
        for piece in pieces
    ):
        return ()
    # A binding imported with ``from pkg import name`` can name either a
    # submodule or a value; probe both interpretations by starting at the
    # full chain and walking back. Attribute installs omit only the replaced
    # leaf, then likewise try every valid module prefix.
    module_pieces = (
        pieces if install.kind in ("module", "binding") else pieces[:-1]
    )
    if not module_pieces:
        return ()
    candidates: list[str] = []
    for length in range(len(module_pieces), 0, -1):
        module_path = "/".join(module_pieces[:length])
        candidates.extend(
            (
                f"{module_path}.py",
                f"{module_path}/__init__.py",
                f"src/{module_path}.py",
                f"src/{module_path}/__init__.py",
            )
        )
    return tuple(
        dict.fromkeys(
            safe
            for candidate in candidates
            if (safe := _safe_repo_path(candidate)) is not None
        )
    )


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
    head_exists=None,
    head_duplicate_searcher=None,
) -> IR:
    g = DiffGlobals()
    g.conftest_standin_patches = []
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
    self_roots = set(self_modules or ())
    external_roots = (
        set(known_modules or ()) - self_roots - known_baseline()
    )
    changed_prod_roots = {
        _module_of(change.path).split(".", 1)[0]
        for change in changes
        if change.path.endswith(".py")
        and config.role_of(change.path.replace("\\", "/")) == "prod"
    }
    # A manifest-declared dependency prevents a coincidental conventional
    # path from becoming ownership evidence. Manifest self-roots and files
    # actually changed under the configured production role are independent,
    # positive repository evidence.
    owned_roots = self_roots | changed_prod_roots
    g.first_party_roots = tuple(sorted(root for root in owned_roots if root))
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
    # Security-sensitive side reads cannot key a rename's base bytes under
    # its destination path. Preserve actual path presence independently:
    # ``old_path`` exists only at base and ``path`` only at head.
    security_raw_sides: tuple[dict[str, bytes], dict[str, bytes]] = ({}, {})
    security_changed_paths: set[str] = set()
    for candidate in changes:
        head_path = candidate.path.replace("\\", "/")
        base_path = (candidate.old_path or candidate.path).replace("\\", "/")
        security_changed_paths.update((base_path, head_path))
        if candidate.before is not None:
            security_raw_sides[0][base_path] = candidate.before
        if candidate.after is not None:
            security_raw_sides[1][head_path] = candidate.after
    security_head_memo: dict[str, bytes | None] = {}

    def _read_head_security(
        path: str, *, expected: bool = False, searched: bool = False
    ) -> bytes | None:
        """Uncapped head read that distinguishes absence from read failure."""
        safe_path = _safe_repo_path(path)
        if safe_path is None:
            # Search results and string patch targets are untrusted.  An
            # invalid repository-relative path is not an ownership/provider
            # candidate and must never reach head_exists/head_reader.
            return None
        path = safe_path
        failure = (
            f"head reader could not read searched test candidate: {path}"
            if searched
            else f"head reader could not read existing path: {path}"
        )
        if path in security_head_memo:
            data = security_head_memo[path]
            if data is None and expected:
                raise EngineError(failure)
            return data
        known_exists = (
            bool(head_exists(path)) if head_exists is not None else None
        )
        if known_exists is False:
            if expected:
                raise EngineError(failure)
            security_head_memo[path] = None
            return None
        if head_reader is None:
            if expected or known_exists:
                raise EngineError(failure)
            security_head_memo[path] = None
            return None
        try:
            data = head_reader(path)
        except EngineError:
            raise
        except OSError as exc:
            raise EngineError(
                f"head reader could not read existing path: {path}"
            ) from exc
        if data is None and (expected or known_exists):
            raise EngineError(failure)
        security_head_memo[path] = data
        return data

    oracle_memo: dict[tuple[str, int], ParsedFile | None] = {}
    oracle_head_reads = [0]

    def _oracle_file(opath: str, side: int) -> ParsedFile | None:
        """A test/conftest module parsed for its oracle carriers, or None.

        side 0 = base, 1 = head. A file outside the diff is identical on both
        sides, so one memo entry — and one head read — serves base and head
        alike. The entry used to be keyed per side, which let the before pass
        drain the shared read budget and the after pass resolve the same
        helper to nothing: every inherited assert became a phantom
        ASSERT_REMOVED on any edit to the importing file, black's trio being
        16 of 74 field-run blocks (R1). A file *added* by the diff has no
        base half, which is what makes an extraction's before side resolve
        to nothing — correctly, so in-diff files keep their per-side halves.

        Role is a pure function of the path and is checked before the read:
        a prod module or a nonexistent sibling candidate must not spend the
        budget on a file that could never carry an oracle.
        """
        in_diff = opath in security_changed_paths
        key = (opath, side if in_diff else -1)
        if key in oracle_memo:
            return oracle_memo[key]
        parsed: ParsedFile | None = None
        if config.role_of(opath) not in ("test", "conftest"):
            oracle_memo[key] = None
            return None
        if in_diff:
            data = security_raw_sides[side].get(opath)
        elif head_reader is not None and oracle_head_reads[0] < _MAX_ORACLE_READS:
            oracle_head_reads[0] += 1
            data = _read_head_security(opath)
        else:
            data = None
        if data is not None:
            parsed = parse_python(
                data, collect_tests=True, conftest=opath.endswith("conftest.py")
            )
            if not parsed.parse_ok:
                parsed = None
        oracle_memo[key] = parsed
        return parsed

    security_oracle_memo: dict[tuple[str, int], ParsedFile | None] = {}

    def _security_oracle_file(opath: str, side: int = 1) -> ParsedFile | None:
        """Uncapped, side-aware provider inventory for stand-in decisions.

        Paths outside the diff have identical base/head bytes, both read from
        the head snapshot.  A changed conftest must instead expose its actual
        before and after fixture graphs; borrowing the head graph for both
        sides erases dependency-only activation events.
        """
        opath = opath.replace("\\", "/")
        key = (opath, side if opath in security_changed_paths else -1)
        if key in security_oracle_memo:
            return security_oracle_memo[key]
        if config.role_of(opath) not in ("test", "conftest"):
            security_oracle_memo[key] = None
            return None
        if opath in security_changed_paths:
            data = security_raw_sides[side].get(opath)
        else:
            data = _read_head_security(opath)
        parsed = None
        if data is not None:
            candidate = parse_python(
                data, collect_tests=True, conftest=opath.endswith("conftest.py")
            )
            if candidate.parse_ok:
                parsed = candidate
        security_oracle_memo[key] = parsed
        return parsed

    # Pytest discovers fixtures from final module/class attributes in ``dir``
    # order. Multiple Python carriers may therefore export a stack under one
    # public fixture name: the last is selected normally, while its same-name
    # dependency deliberately resolves the preceding carrier. ParsedFile's
    # public-name dictionaries are intentionally compact/lossy, so reconstruct
    # this ordered registration identity only for security fixture resolution.
    fixture_registration_memo: dict[
        tuple[str, int],
        dict[str, dict[str, tuple[_FixtureProvider, ...]]],
    ] = {}

    def _fixture_registrations(
        source_path: str, side: int
    ) -> dict[str, dict[str, tuple[_FixtureProvider, ...]]]:
        source_path = source_path.replace("\\", "/")
        key = (
            source_path,
            side if source_path in security_changed_paths else -1,
        )
        if key in fixture_registration_memo:
            return fixture_registration_memo[key]
        parsed = _security_oracle_file(source_path, side)
        if parsed is None:
            fixture_registration_memo[key] = {}
            return {}
        data = (
            security_raw_sides[side].get(source_path)
            if source_path in security_changed_paths
            else _read_head_security(source_path)
        )
        if data is None:
            fixture_registration_memo[key] = {}
            return {}
        try:
            tree = ast.parse(_decode(data))
        except (SyntaxError, RecursionError, ValueError, MemoryError):
            # ``parsed`` above was successful, so this is defensive only. A
            # missing registration map keeps the already parsed conservative
            # provider graph rather than inventing a different winner.
            fixture_registration_memo[key] = {}
            return {}
        definition_imports = _definition_import_maps(tree)
        registrations: dict[
            str, dict[str, tuple[_FixtureProvider, ...]]
        ] = {}

        def collect_container(
            container: ast.Module | ast.ClassDef,
            container_name: str,
            *,
            class_member: bool,
        ) -> None:
            live = _module_callable_scopes(container)
            candidates: dict[str, list[_FixtureProvider]] = {}
            provider_prefix = (
                f"{source_path}::{container_name}"
                if container_name
                else source_path
            )
            for carrier, node in live.items():
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                exact = definition_imports.get(id(node))
                public_name = _fixture_public_name(node, exact)
                if public_name is None:
                    continue
                dependencies = tuple(
                    sorted(
                        _required_injected_parameters(
                            node,
                            class_member=class_member,
                            definition_imports=exact,
                        )
                    )
                )
                body = tuple(
                    statement
                    for statement in node.body
                    if not (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str)
                    )
                )
                transparent_receiver = None
                if (
                    public_name in ("monkeypatch", "mocker")
                    and public_name in dependencies
                    and len(body) == 1
                ):
                    statement = body[0]
                    value = (
                        statement.value
                        if isinstance(statement, ast.Return)
                        else (
                            statement.value.value
                            if isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Yield)
                            else None
                        )
                    )
                    if isinstance(value, ast.Name) and value.id == public_name:
                        transparent_receiver = public_name
                start_line = min(
                    (
                        getattr(decorator, "lineno", node.lineno)
                        for decorator in node.decorator_list
                    ),
                    default=node.lineno,
                )
                candidates.setdefault(public_name, []).append(
                    _FixtureProvider(
                        provider_id=(
                            f"{provider_prefix}::<fixture:{carrier}>"
                        ),
                        public_name=public_name,
                        dependencies=dependencies,
                        autouse=_fixture_is_autouse(node, exact),
                        start_line=start_line,
                        end_line=getattr(
                            node, "end_lineno", node.lineno
                        ),
                        transparent_receiver=transparent_receiver,
                    )
                )
            registrations[container_name] = {
                public_name: tuple(
                    sorted(rows, key=lambda row: row.provider_id)
                )
                for public_name, rows in candidates.items()
            }
            for carrier, node in live.items():
                if not isinstance(node, ast.ClassDef):
                    continue
                child_name = (
                    f"{container_name}.{carrier}"
                    if container_name
                    else carrier
                )
                collect_container(
                    node, child_name, class_member=True
                )

        collect_container(tree, "", class_member=False)
        fixture_registration_memo[key] = registrations
        return registrations

    def _fixture_provider_for_install(
        source_path: str, side: int, install: StandinInstall
    ) -> _FixtureProvider | None:
        public_owner = (install.owner or "").rsplit(".", 1)[-1]
        for container in _fixture_registrations(
            source_path, side
        ).values():
            for provider in container.get(public_owner, ()):
                if (
                    provider.start_line
                    <= install.position[0]
                    <= provider.end_line
                ):
                    return provider
        return None

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
            requested = list(getattr(uside, "fixtures", uside.params))
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
            if (
                conftest_path in security_changed_paths
                and conftest_path != tpath
            ):
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

    fixture_environment_memo: dict[
        tuple[str, int], tuple[_FixtureProvider, ...]
    ] = {}

    def _ancestor_conftests(path: str) -> tuple[str, ...]:
        """Root-to-nearest conftest paths that pytest can expose to path."""
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        parts = directory.split("/") if directory else []
        return tuple(
            dict.fromkeys(
                (
                    "conftest.py",
                    *(
                        "/".join(parts[: depth + 1]) + "/conftest.py"
                        for depth in range(len(parts))
                    ),
                )
            )
        )

    def _fixture_environment(tpath: str, parsed: ParsedFile, side: int):
        """Ordered conftest/module fixture providers on one repository side."""
        key = (tpath, side)
        if key in fixture_environment_memo:
            return fixture_environment_memo[key]
        providers: list[_FixtureProvider] = []
        for path in _ancestor_conftests(tpath):
            candidate = _security_oracle_file(path, side)
            if candidate is not None and candidate.parse_ok:
                registrations = _fixture_registrations(path, side)
                module_registrations = registrations.get("", {})
                if module_registrations:
                    providers.extend(
                        provider
                        for stack in module_registrations.values()
                        for provider in stack
                    )
                else:
                    providers.extend(
                        _FixtureProvider(
                            provider_id=path,
                            public_name=name,
                            dependencies=dependencies,
                            autouse=name in candidate.autouse_fixtures,
                            start_line=0,
                            end_line=0,
                        )
                        for name, dependencies in (
                            candidate.fixture_dependencies.items()
                        )
                    )
        module_registrations = _fixture_registrations(tpath, side).get(
            "", {}
        )
        if module_registrations:
            providers.extend(
                provider
                for stack in module_registrations.values()
                for provider in stack
            )
        else:
            providers.extend(
                _FixtureProvider(
                    provider_id=tpath,
                    public_name=name,
                    dependencies=dependencies,
                    autouse=name in parsed.autouse_fixtures,
                    start_line=0,
                    end_line=0,
                )
                for name, dependencies in parsed.fixture_dependencies.items()
            )
        environment = tuple(providers)
        fixture_environment_memo[key] = environment
        return environment

    def _fixture_resolution(
        tpath: str,
        parsed: ParsedFile,
        unit_side,
        side: int,
    ) -> _FixtureResolution:
        """Provider-aware pytest fixture closure for one collected unit.

        A flat ``name -> provider`` map loses three real pytest semantics:
        class-local fixtures shadow conftest fixtures only for their class;
        direct parametrization installs a pseudo-fixture visible to another
        fixture's dependency; and ``def f(f)`` deliberately requests the
        previous overridden provider. Resolve a layered provider stack while
        retaining ancestor autouse names as activation roots.
        """
        fixture_providers = list(
            _fixture_environment(tpath, parsed, side)
        )
        registrations = _fixture_registrations(tpath, side)
        for class_name, dependencies, autouse in (
            getattr(unit_side, "standin_fixture_layers", ()) or ()
        ):
            class_registrations = registrations.get(class_name, {})
            if class_registrations:
                fixture_providers.extend(
                    provider
                    for stack in class_registrations.values()
                    for provider in stack
                )
            else:
                fixture_providers.extend(
                    _FixtureProvider(
                        provider_id=f"{tpath}::{class_name}",
                        public_name=name,
                        dependencies=fixture_dependencies,
                        autouse=name in autouse,
                        start_line=0,
                        end_line=0,
                    )
                    for name, fixture_dependencies in dependencies.items()
                )
        parameter_providers = (
            getattr(unit_side, "standin_parameter_providers", None) or {}
        )
        direct_parameters = {
            name: ()
            for name, provider in parameter_providers.items()
            if provider and provider[0] == "parametrize"
        }
        if direct_parameters:
            fixture_providers.extend(
                _FixtureProvider(
                    provider_id=f"{tpath}::<parametrize:{name}>",
                    public_name=name,
                    dependencies=(),
                    autouse=False,
                    start_line=0,
                    end_line=0,
                )
                for name in direct_parameters
            )

        providers: dict[str, list[int]] = {}
        autouse_names: set[str] = set()
        for index, provider in enumerate(fixture_providers):
            providers.setdefault(provider.public_name, []).append(index)
            if provider.autouse:
                autouse_names.add(provider.public_name)

        def resolve(name: str, before: int | None = None) -> int | None:
            candidates = providers.get(name, ())
            for index in reversed(candidates):
                if before is None or index < before:
                    return index
            return None

        trusted_memo: dict[int, bool] = {}

        def trusted_receiver(provider_index: int) -> bool:
            if provider_index in trusted_memo:
                return trusted_memo[provider_index]
            provider = fixture_providers[provider_index]
            trusted = False
            if (
                provider.transparent_receiver
                == provider.public_name
            ):
                previous = resolve(
                    provider.public_name, provider_index
                )
                trusted = (
                    previous is None or trusted_receiver(previous)
                )
            trusted_memo[provider_index] = trusted
            return trusted

        pending: list[tuple[str, int]] = []
        for name in sorted(
            set(getattr(unit_side, "fixtures", unit_side.params))
            | autouse_names
        ):
            provider_index = resolve(name)
            if provider_index is not None:
                pending.append((name, provider_index))

        active: set[tuple[str, str]] = set()
        trusted_active: set[tuple[str, str]] = set()
        visited: set[tuple[str, int]] = set()
        while pending:
            name, provider_index = pending.pop()
            state = (name, provider_index)
            if state in visited:
                continue
            visited.add(state)
            provider = fixture_providers[provider_index]
            token = (provider.provider_id, name)
            active.add(token)
            if trusted_receiver(provider_index):
                trusted_active.add(token)
            for dependency in provider.dependencies:
                dependency_index = resolve(
                    dependency,
                    provider_index if dependency == name else None,
                )
                if dependency_index is not None:
                    pending.append((dependency, dependency_index))
        return _FixtureResolution(
            active=frozenset(active),
            trusted_receivers=frozenset(trusted_active),
            provider_order=tuple(
                (provider.provider_id, provider.public_name)
                for provider in fixture_providers
            ),
        )

    def _repo_fixture_shadows_receiver(
        install: StandinInstall,
        resolution: _FixtureResolution,
        *,
        current_provider: tuple[str, str] | None = None,
    ) -> bool:
        """Whether pytest resolves an API receiver to repository code.

        A fixture may override itself while requesting the prior definition:
        ``def monkeypatch(monkeypatch)`` receives its parent/plugin fixture,
        not its own return value. The currently executing provider is therefore
        excluded, while any earlier active repository provider still shadows
        the builtin/plugin receiver.
        """
        receiver = install.api_fixture_receiver
        if receiver is None:
            return False
        eligible = resolution.active
        if current_provider is not None:
            try:
                current_index = resolution.provider_order.index(
                    current_provider
                )
            except ValueError:
                pass
            else:
                # ``def monkeypatch(monkeypatch)`` requests the preceding
                # fixture definition. Providers registered after this one may
                # depend on and execute it, but cannot flow backwards into its
                # receiver argument and therefore are consumers, not shadows.
                eligible = eligible & frozenset(
                    resolution.provider_order[:current_index]
                )
        return any(
            fixture_name == receiver
            and (provider, fixture_name) != current_provider
            and (provider, fixture_name)
            not in resolution.trusted_receivers
            for provider, fixture_name in eligible
        )

    def _filter_unit_standin_installs(
        test_path: str, parsed: ParsedFile, side: int
    ) -> None:
        """Apply local fixture-provider and API-receiver resolution."""
        def fixture_provider(
            install: StandinInstall,
        ) -> _FixtureProvider | None:
            if install.scope not in ("fixture", "class_fixture"):
                return None
            return _fixture_provider_for_install(
                test_path, side, install
            )

        def current_provider(
            install: StandinInstall,
            provider: _FixtureProvider | None,
        ) -> tuple[str, str] | None:
            if (
                provider is None
                or provider.public_name
                != install.api_fixture_receiver
            ):
                return None
            return (provider.provider_id, provider.public_name)

        # The frontend can attach fixture installs that its same-file graph
        # proves active. A conftest fixture may also request a fixture supplied
        # by the consuming test module/class, however; only the engine has that
        # cross-file graph. Retain all local fixture-scoped candidates here and
        # let the side-aware provider resolution below select the ones that
        # actually execute for each unit.
        fixture_candidates = tuple(
            install
            for install in parsed.standin_installs
            if install.scope in ("fixture", "class_fixture")
        )
        for unit in parsed.units:
            unit_side = unit.side
            installs = tuple(
                dict.fromkeys(
                    (
                        *(unit_side.standin_installs or ()),
                        *fixture_candidates,
                    )
                )
            )
            if not installs:
                continue
            resolution = _fixture_resolution(
                test_path, parsed, unit_side, side
            )
            filtered: list[StandinInstall] = []
            for install in installs:
                provider = fixture_provider(install)
                if (
                    provider is not None
                    and (provider.provider_id, provider.public_name)
                    not in resolution.active
                ):
                    continue
                if _repo_fixture_shadows_receiver(
                    install,
                    resolution,
                    current_provider=current_provider(
                        install, provider
                    ),
                ):
                    continue
                filtered.append(install)
            unit_side.standin_installs = tuple(filtered)

    changed_conftest_paths: set[str] = set()
    test_side_paths: dict[str, tuple[str, str]] = {}
    source_counts = Counter(
        data
        for candidate in changes
        for data in (candidate.before, candidate.after)
        if data is not None
    )
    repeated_sources = {
        data for data, count in source_counts.items() if count > 1
    }
    parse_templates: dict[tuple[bytes, bool, bool], ParsedFile] = {}

    def _parse_changed_python(
        data: bytes, *, collect_tests: bool, conftest: bool
    ) -> ParsedFile:
        """Return an independent parse, reusing only repeated source bytes."""
        if data not in repeated_sources:
            return parse_python(
                data, collect_tests=collect_tests, conftest=conftest
            )
        key = (data, collect_tests, conftest)
        template = parse_templates.get(key)
        if template is not None:
            return copy.deepcopy(template)
        parsed = parse_python(
            data, collect_tests=collect_tests, conftest=conftest
        )
        # The caller enriches each ParsedFile with side/path-specific oracle
        # and fixture data. Retain an untouched template before returning the
        # first instance for those mutations.
        parse_templates[key] = copy.deepcopy(parsed)
        return parsed

    for change in sorted(_expand_renames(changes, config), key=lambda c: c.path):
        path = change.path.replace("\\", "/")
        old_path = (change.old_path or path).replace("\\", "/")
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
        if is_js_test_path(path):
            role = "test"
        is_js_test = is_js_test_path(path)

        before_parsed: ParsedFile | None = None
        after_parsed: ParsedFile | None = None
        if is_python:
            is_conftest = role == "conftest"
            collect = is_conftest or (role == "test" and collectable(path))
            if (
                change.before is not None
                and change.after is not None
                and change.before == change.after
            ):
                # Some API producers retain byte-identical modified/renamed
                # entries. Parsing is pure and path-independent; clone the
                # result so side-specific oracle/fixture enrichment below
                # still mutates independent objects.
                before_parsed = _parse_changed_python(
                    change.before, collect_tests=collect, conftest=is_conftest
                )
                after_parsed = copy.deepcopy(before_parsed)
            else:
                if change.before is not None:
                    before_parsed = _parse_changed_python(
                        change.before,
                        collect_tests=collect,
                        conftest=is_conftest,
                    )
                if change.after is not None:
                    after_parsed = _parse_changed_python(
                        change.after,
                        collect_tests=collect,
                        conftest=is_conftest,
                    )
        elif is_js_test:
            if change.before is not None:
                before_parsed = parse_javascript(change.before)
            if change.after is not None:
                after_parsed = parse_javascript(change.after)

        if after_parsed is not None and after_parsed.parse_ok:
            after_by_path[path] = after_parsed
        if before_parsed is not None and before_parsed.parse_ok:
            before_by_path[path] = before_parsed

        if is_python and role == "test" and collect:
            if before_parsed is not None:
                _merge_crossfile_oracles(old_path, before_parsed, 0)
                _filter_unit_standin_installs(
                    old_path, before_parsed, 0
                )
            if after_parsed is not None:
                _merge_crossfile_oracles(path, after_parsed, 1)
                _filter_unit_standin_installs(path, after_parsed, 1)

        file_ir = align_file(path, role, change.status, before_parsed, after_parsed)
        parsed_for_helpers = after_parsed if after_parsed and after_parsed.parse_ok else before_parsed
        if parsed_for_helpers is not None and parsed_for_helpers.parse_ok:
            file_ir.helper_calls = dict(parsed_for_helpers.helper_calls)
            if is_python:
                file_ir.standin_imports = dict(parsed_for_helpers.import_bindings)
        ir.files.append(file_ir)
        if is_python and not file_ir.parse_ok:
            ir.skipped_files.append(path)
            # A test file checkwash cannot parse is a test file checkwash did
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
        if role == "test":
            test_side_paths[path] = (old_path, path)
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

        if path in MANIFESTS and _deps_differ(change.before, change.after, path):
            g.dependency_manifest_changed = True

        # Preserve the serialized IR-v1 field exactly: its contract is the
        # original raw first-party monkeypatch-call census, not the richer
        # reachability/lifetime result introduced by this family.
        if role == "conftest" and change.after is not None:
            legacy_first_party = frozenset(
                candidate.path.replace("\\", "/").split("/")[0].removesuffix(".py")
                for candidate in changes
            ) | frozenset(
                _module_of(existing.path).split(".")[0]
                for existing in ir.files
                if existing.role == "prod"
            )
            legacy_before = (
                set(conftest_patch_targets(change.before, legacy_first_party))
                if change.before is not None
                else set()
            )
            for text in conftest_patch_targets(change.after, legacy_first_party):
                if text not in legacy_before:
                    g.conftest_prod_patches.append((path, text))

        if role == "conftest" and (
            change.before != change.after or old_path != path
        ):
            # A graph-only edit can activate an unchanged ancestor stand-in;
            # retain the changed path even when this file adds no install.
            changed_conftest_paths.update((old_path, path))

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
                # parse failure: checkwash cannot tell repair from decoy
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
            if path in (".checkwash/allow.toml", ".greenwash/allow.toml"):
                appended = _classify_allowlist_change(change.before, change.after)
                if appended is not None:
                    g.exemptions_added.extend(appended)
                    g.exemption_ledger_path = path
                else:
                    g.guardrail_files_changed.append(path)
            else:
                g.guardrail_files_changed.append(path)
            if not change.before:
                g.guardrail_files_created.append(path)
                if path in _OWN_CONFIG_PATHS and _created_config_loosens(change.after):
                    g.guardrail_configs_created_loosening.append(path)
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

    # A conftest effect can become dangerous without being textually new:
    # an existing test can request its fixture for the first time, or a
    # changed adapter/autouse fixture can acquire a dependency on it. Build
    # base and head fixture environments independently, then compare only the
    # effects that actually execute for each aligned, live test unit.
    conftest_events: dict[
        tuple[str, tuple[str, str, str, str, str, bool]],
        tuple[str, StandinInstall],
    ] = {}

    def _applicable_conftest_installs(
        test_path: str,
        parsed: ParsedFile,
        unit_side,
        side: int,
    ) -> tuple[tuple[str, StandinInstall], ...]:
        resolution = _fixture_resolution(
            test_path, parsed, unit_side, side
        )
        applicable: list[tuple[str, StandinInstall]] = []
        for conftest_path in _ancestor_conftests(test_path):
            conftest = _security_oracle_file(conftest_path, side)
            if conftest is None:
                continue
            for install in conftest.standin_installs:
                # A conftest-local binding does not replace the binding in a
                # separately imported test module.
                if install.kind == "binding":
                    continue
                # Pytest registers the repository/root and immediate test
                # conftests during initial discovery. A deeper provider is
                # commonly imported only after configure/sessionstart have
                # fired, so its early-hook body is not a definite effect.
                # Module bodies, fixtures, and runtest hooks have later,
                # independently modelled lifecycles and remain eligible.
                if (
                    install.scope == "hook"
                    and install.owner in _NON_HISTORIC_EARLY_CONFTEST_HOOKS
                    and not _initial_conftest_for_default_collection(
                        conftest_path
                    )
                ):
                    continue
                public_owner = (install.owner or "").rsplit(".", 1)[-1]
                fixture_provider = (
                    _fixture_provider_for_install(
                        conftest_path, side, install
                    )
                    if install.scope in ("fixture", "class_fixture")
                    else None
                )
                provider_token = (
                    (
                        fixture_provider.provider_id,
                        fixture_provider.public_name,
                    )
                    if fixture_provider is not None
                    else (conftest_path, public_owner)
                )
                current_provider = (
                    provider_token
                    if public_owner == install.api_fixture_receiver
                    else None
                )
                if _repo_fixture_shadows_receiver(
                    install,
                    resolution,
                    current_provider=current_provider,
                ):
                    # The frontend's receiver proof assumes pytest's builtin
                    # monkeypatch or pytest-mock's mocker fixture. A visible
                    # repository/class/direct-param provider with that name
                    # wins pytest resolution, so the arbitrary receiver no
                    # longer proves that this call installs anything.
                    continue
                applies = (
                    provider_token in resolution.active
                    if install.scope in ("fixture", "class_fixture")
                    else install_applies(install, unit_side)
                )
                if applies:
                    applicable.append((conftest_path, install))
        return tuple(
            sorted(
                applicable,
                key=lambda item: (
                    item[1].effect_identity,
                    item[0],
                    item[1].text,
                    item[1].position,
                ),
            )
        )

    # Changed tests are already in memory. A changed conftest can also affect
    # unchanged tests, so derive literal oracle needles from both sides of it
    # and every ancestor (an edited nested adapter can activate a root
    # fixture), then inventory all matching head tests in one batch.
    test_pairs: dict[
        str, tuple[str, str, ParsedFile, ParsedFile, tuple]
    ] = {}
    files_by_path = {file.path: file for file in ir.files}
    for test_path in sorted(set(before_by_path) & set(after_by_path)):
        if config.role_of(test_path) != "test" or not collectable(test_path):
            continue
        file = files_by_path.get(test_path)
        if file is None:
            continue
        pairs = tuple(
            (unit.before, unit.after)
            for unit in file.units
            if unit.before is not None and unit.after is not None
        )
        if pairs:
            before_test_path, after_test_path = test_side_paths.get(
                test_path, (test_path, test_path)
            )
            test_pairs[test_path] = (
                before_test_path,
                after_test_path,
                before_by_path[test_path],
                after_by_path[test_path],
                pairs,
            )

    search_installs: list[StandinInstall] = []
    fixture_provider_needles: set[str] = set()
    receiver_transition_needles: set[str] = set()
    for changed_path in sorted(changed_conftest_paths):
        for conftest_path in _ancestor_conftests(changed_path):
            for side in (0, 1):
                parsed = _security_oracle_file(conftest_path, side)
                if parsed is not None:
                    search_installs.extend(
                        install
                        for install in parsed.standin_installs
                        if install.kind != "binding"
                    )
        for side in (0, 1):
            changed_parsed = _security_oracle_file(changed_path, side)
            if changed_parsed is None:
                continue
            receiver_transition_needles.update(
                {"monkeypatch", "mocker"}
                & (
                    set(changed_parsed.fixture_dependencies)
                    | set(
                        _fixture_registrations(changed_path, side).get(
                            "", {}
                        )
                    )
                )
            )
            fixture_provider_needles.update(
                changed_parsed.fixture_dependencies
            )
            fixture_provider_needles.update(
                dependency
                for dependencies in changed_parsed.fixture_dependencies.values()
                for dependency in dependencies
                if dependency not in ("monkeypatch", "mocker", "request")
            )

    # A parent fixture resolves non-self dependencies in the consuming test's
    # context, so a changed root adapter can activate an installing fixture in
    # an unchanged descendant conftest. Discover provider files by fixture
    # name first, then use their concrete target names for the test inventory.
    def _below_changed_conftest(path: str) -> bool:
        return any(
            not directory or path.startswith(directory + "/")
            for changed_path in changed_conftest_paths
            for directory in (
                changed_path.rsplit("/", 1)[0]
                if "/" in changed_path
                else "",
            )
        )

    test_provider_candidates: set[str] = set()
    if (
        fixture_provider_needles
        and head_searcher is not None
        and head_reader is not None
    ):
        provider_candidates = sorted(
            {
                safe
                for candidate in head_searcher(
                    sorted(fixture_provider_needles)
                )
                if (safe := _safe_repo_path(candidate)) is not None
                and safe not in security_changed_paths
                and (
                    (
                        safe.endswith("conftest.py")
                        and config.role_of(safe) == "conftest"
                    )
                    or (
                        safe.endswith(".py")
                        and config.role_of(safe) == "test"
                        and collectable(safe)
                    )
                )
                and _below_changed_conftest(safe)
            }
        )
        for provider_path in provider_candidates:
            data = _read_head_security(
                provider_path, expected=True
            )
            assert data is not None
            parsed = _security_oracle_file(provider_path, 1)
            if parsed is None:
                provider_kind = (
                    "conftest"
                    if config.role_of(provider_path) == "conftest"
                    else "test fixture"
                )
                raise EngineError(
                    "head reader could not parse searched "
                    + provider_kind
                    + " provider: "
                    + provider_path
                )
            registrations = _fixture_registrations(
                provider_path, 1
            )
            provided_names = set(parsed.fixture_dependencies)
            provided_names.update(
                public_name
                for container in registrations.values()
                for public_name in container
            )
            if not provided_names.intersection(
                fixture_provider_needles
            ):
                continue
            is_test_provider = config.role_of(provider_path) == "test"
            if is_test_provider:
                # The provider and its consuming oracle may live in this very
                # test module. Retain it for direct side-aware evaluation even
                # if the target is referenced through an alias that a literal
                # target search would not rediscover.
                test_provider_candidates.add(provider_path)
            search_installs.extend(
                install
                for install in parsed.standin_installs
                if (
                    install.scope in ("fixture", "class_fixture")
                    if is_test_provider
                    else install.kind != "binding"
                )
            )
    needles = sorted(
        receiver_transition_needles
        | {
            needle
            for install in search_installs
            for needle in (
                install.attr if install.attr != "*" else "",
                install.target.rsplit(".", 1)[-1],
            )
            if needle
        }
    )
    if (
        (needles or test_provider_candidates)
        and head_searcher is not None
        and head_reader is not None
    ):
        diff_paths = set(security_changed_paths)
        searched_test_candidates = (
            head_searcher(needles) if needles else ()
        )
        candidates = sorted(
            test_provider_candidates
            | {
                safe
                for candidate in searched_test_candidates
                if (safe := _safe_repo_path(candidate)) is not None
                and safe not in diff_paths
                and safe.endswith(".py")
                and config.role_of(safe) == "test"
                and collectable(safe)
                and _below_changed_conftest(safe)
            }
        )
        # This is a security inventory, not an optional duplicate credit. Do
        # not cap it by path count or file size; every searched result is read
        # through the fail-closed safe-path callback.
        for test_path in candidates:
            data = _read_head_security(
                test_path, expected=True, searched=True
            )
            assert data is not None  # expected=True makes absence an error
            before_parsed = parse_python(data, collect_tests=True)
            after_parsed = parse_python(data, collect_tests=True)
            if not before_parsed.parse_ok or not after_parsed.parse_ok:
                raise EngineError(
                    "head reader could not parse searched test candidate: "
                    + test_path
                )
            _merge_crossfile_oracles(test_path, before_parsed, 0)
            _merge_crossfile_oracles(test_path, after_parsed, 1)
            _filter_unit_standin_installs(test_path, before_parsed, 0)
            _filter_unit_standin_installs(test_path, after_parsed, 1)
            before_units = {
                unit.qualname: unit.side for unit in before_parsed.units
            }
            after_units = {
                unit.qualname: unit.side for unit in after_parsed.units
            }
            pairs = tuple(
                (before_units[name], after_units[name])
                for name in sorted(set(before_units) & set(after_units))
            )
            if pairs:
                test_pairs[test_path] = (
                    test_path,
                    test_path,
                    before_parsed,
                    after_parsed,
                    pairs,
                )
            if any(
                new_unit_standin_installs(before_side, after_side)
                for before_side, after_side in pairs
            ):
                # The source bytes are unchanged, but a changed conftest can
                # remove a repository fixture that shadowed pytest's trusted
                # monkeypatch/mocker provider.  That environment transition
                # makes an existing local call a newly operative stand-in, so
                # expose the aligned file to TEST_PATCHES_SUBJECT exactly as
                # we do for an in-diff test edit.
                before_by_path[test_path] = before_parsed
                after_by_path[test_path] = after_parsed
                searched_file = align_file(
                    test_path,
                    "test",
                    "modified",
                    before_parsed,
                    after_parsed,
                )
                searched_file.helper_calls = dict(
                    after_parsed.helper_calls
                )
                searched_file.standin_imports = dict(
                    after_parsed.import_bindings
                )
                ir.files.append(searched_file)
                files_by_path[test_path] = searched_file
                g.test_file_imports[test_path] = list(
                    after_parsed.imports
                )

    for test_path, (
        before_test_path,
        after_test_path,
        before_parsed,
        after_parsed,
        pairs,
    ) in sorted(test_pairs.items()):
        # The fixture/oracle comparison below resolves constants and walks
        # every aligned unit. Most diffs have no conftest stand-in at all;
        # prove that once from the small ancestor chain so the many-file path
        # stays linear instead of calling `_gate_constants` N times against
        # an N-file parse map.
        if not any(
            candidate is not None and candidate.standin_installs
            for side, side_path in (
                (0, before_test_path),
                (1, after_test_path),
            )
            for conftest_path in _ancestor_conftests(side_path)
            for candidate in (
                _security_oracle_file(conftest_path, side),
            )
        ):
            continue
        before_constants = _gate_constants(
            before_parsed, before_by_path, None
        )
        after_constants = _gate_constants(
            after_parsed, after_by_path, head_reader
        )
        for before_side, after_side in pairs:
            if not unit_is_live(after_side, after_constants):
                continue
            before_entries = (
                _applicable_conftest_installs(
                    before_test_path, before_parsed, before_side, 0
                )
                if unit_is_live(before_side, before_constants)
                else ()
            )
            after_entries = _applicable_conftest_installs(
                after_test_path, after_parsed, after_side, 1
            )
            if not after_entries:
                continue
            before_imports = (
                before_side.standin_imports
                if before_side.standin_imports is not None
                else before_parsed.import_bindings
            )
            after_imports = (
                after_side.standin_imports
                if after_side.standin_imports is not None
                else after_parsed.import_bindings
            )
            selected = new_reaching_effects(
                before_side,
                after_side,
                before_imports,
                after_imports,
                before_installs=tuple(
                    install for _path, install in before_entries
                ),
                after_installs=tuple(
                    install for _path, install in after_entries
                ),
            )
            for event in selected:
                # Preserve source attribution after the shared semantic API
                # groups alternative instances by effect identity. Prefer an
                # instance that really reaches this unit, then deterministic
                # path/text order.
                reaching = [
                    (path, install)
                    for path, install in after_entries
                    if install.effect_identity == event.effect_identity
                    and install_reaches(
                        install, after_side, after_imports
                    )
                ]
                if not reaching:
                    continue
                path, install = min(
                    reaching,
                    key=lambda item: (
                        item[0],
                        item[1].text,
                        item[1].position,
                    ),
                )
                conftest_events.setdefault(
                    (path, install.effect_identity), (path, install)
                )

    # The manifest project name is the strongest ownership source, but test
    # fixtures often model a src-layout package without including a manifest.
    # A readable canonical module path in the head snapshot is positive local
    # evidence too. Missing paths do not become ownership by subtraction.
    # Crucially, a conftest candidate reaches this set only after applicability
    # and oracle reach have both been proven; dormant fixtures must not cause
    # N x git ownership probes.
    ownership_candidates = {
        install for _path, install in conftest_events.values()
    }
    # TEST_PATCHES_SUBJECT can only consume a newly added patch on an existing
    # aligned unit whose oracle reaches that exact target. Apply those two
    # in-memory predicates before conventional-path ownership probes: existing
    # hygiene mocks and unrelated collaborator stubs must not cause git reads.
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.before is None or unit.after is None:
                continue
            if (
                not (unit.before.standin_installs or ())
                and not (unit.after.standin_installs or ())
                and _provider_context(unit.before)
                == _provider_context(unit.after)
            ):
                continue
            for install in new_unit_standin_installs(
                unit.before, unit.after
            ):
                if install_reaches(
                    install,
                    unit.after,
                    (
                        unit.after.standin_imports
                        if unit.after.standin_imports is not None
                        else file.standin_imports or {}
                    ),
                ):
                    ownership_candidates.add(install)
    if head_reader is not None:
        for install in sorted(
            ownership_candidates,
            key=lambda item: (
                item.effect_identity,
                item.finding_target,
                item.text,
                item.replacement_target or "",
            ),
        ):
            if install.target.startswith((".", "request.module")):
                continue
            root = install.target.split(".", 1)[0]
            if root in owned_roots:
                continue
            if root in external_roots:
                continue
            if any(
                _read_head_security(path) is not None
                for path in _standin_module_paths(install)
            ):
                owned_roots.add(root)
    g.first_party_roots = tuple(sorted(owned_roots))

    assert g.conftest_standin_patches is not None
    g.conftest_standin_patches.extend(
        sorted(
            {
                (path, install.text)
                for path, install in conftest_events.values()
                if target_is_repo_owned(install.target, owned_roots)
            }
        )
    )

    g.conftest_prod_patches.sort()
    assert g.conftest_standin_patches is not None
    g.conftest_standin_patches.sort()
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
            file.module_constants = _canonical_constants(parsed.constants)
            before = before_by_path.get(file.path)
            if before is not None:
                file.constants_before = _gate_constants(before, before_by_path, None)
                file.fixture_defs_before = dict(before.fixture_defs)
                file.module_constants_before = _canonical_constants(before.constants)
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
    duplicate_searcher = head_duplicate_searcher or head_searcher
    if duplicate_searcher is not None and head_reader is not None:
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
                safe
                for candidate in duplicate_searcher(sorted(needles))
                if (safe := _safe_repo_path(candidate)) is not None
                and safe not in diff_paths
                and safe.endswith(".py")
                and config.role_of(safe) == "test"
                and collectable(safe)
            )
            found: set[str] = set()
            for path in candidates[:_MAX_DUP_READS]:
                data = _read_head_security(path)
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
    head_exists=None,
    head_duplicate_searcher=None,
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
        head_exists=head_exists,
        head_duplicate_searcher=head_duplicate_searcher,
    )
    findings = run_detectors(ir, config)
    verdict = apply_gates(ir, findings, contract, config, allow_entries, today)
    return ir, findings, verdict
