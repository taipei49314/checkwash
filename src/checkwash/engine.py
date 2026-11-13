"""Pipeline orchestration: FileChange list → IR → findings → verdict.

Source-agnostic: gitio and the .gwcase runner both produce FileChange lists,
so fixtures exercise the exact same pipeline the CLI runs.

Role / CI / evidence helpers live in checkwash.roles, .ci, .evidence (E5).
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace

from checkwash.allowlist import AllowEntry
from checkwash.change import EngineError, FileChange, UnreadSide
from checkwash.opaque import opaque_error, split_inventory
from checkwash.ci import (
    _ci_base_surface,
    _deps_differ,
    _is_ci_workflow,
    _runs_tests,
    _scan_ci_weakening,
)
from checkwash.ci_control_flow import holds_runner_site
from checkwash.config import Config
from checkwash.policy_shadow import config_transition, shadow_baseline
from checkwash.oracle_credit import mark_contexts
from checkwash.collection_inventory import (
    _runner as _collection_runner,
    collection_inventory_changes,
    collection_sources,
    environment_reached,
    opaque_reached,
)
from checkwash.conftest_context import ConftestContext
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
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.javascript.module_mocks import _EXTENSIONS as _JS_EXTENSIONS, module_mock_events
from checkwash.frontends.javascript.setup_files import is_carrier, listed_setup_files, setup_file_events
from checkwash.frontends.javascript.paths import is_js_test_file, is_js_test_path
from checkwash.frontends.javascript.runners import (
    collected,
    collection_continues,
    focus_is_file_scoped,
    focus_is_innermost,
    may_be_evidenced_test_path,
    runner_evidence,
)
from checkwash.frontends.python.frontend import (
    ParsedFile,
    conftest_patch_targets,
    normalize_source,
    parse_conftest_level,
    parse_python,
)
from checkwash.frontends.python.binding_canonical import binding_key as _binding_key
from checkwash.frontends.python.helper_skips import HelperModule
from checkwash.frontends.python.setup_skip_controls import ConftestLevel, unreadable_level
from checkwash.frontends.python.root_oracles import project_root_oracles, root_caller_unchanged, root_imports, transparent_root_helpers
from checkwash.frontends.python.normalization import mark_normalization_equivalence
from checkwash.frontends.python.param_input_identity import mark_param_input_identity
from checkwash.frontends.python.table_normalization import mark_table_normalization
from checkwash.frontends.python.table_oracles import project_table_consolidation
from checkwash.frontends.python.classic_raises import mark_classic_exception_removal
from checkwash.frontends.python.empty_parameter_sets import mark_empty_parameter_introduction
from checkwash.frontends.python.neutralizing_aliases import mark_neutralizing_aliases
from checkwash.frontends.python.class_exception_aliases import mark_class_exception_aliases
from checkwash.frontends.python.function_exception_aliases import mark_function_exception_aliases
from checkwash.frontends.python.manual_unittest_suites import project_manual_unittest_suites
from checkwash.frontends.python.type_comparison_oracles import mark_type_comparisons
from checkwash.frontends.python.builtin_normalization_oracles import mark_builtin_normalizations
from checkwash.frontends.python.literal_all_oracles import mark_literal_all
from checkwash.frontends.python.empty_length_guards import mark_empty_length_guards
from checkwash.frontends.python.truthiness_oracles import project_truthiness_oracles
from checkwash.frontends.python.standin_installations import installation_events
from checkwash.frontends.python.subject_replacements import subject_replacement_events
from checkwash.frontends.python.callable_fixture_subjects import callable_fixture_subject_events
from checkwash.frontends.python.local_parameter_implementations import local_parameter_implementation_events
from checkwash.frontends.python.fixture_local_implementations import fixture_local_implementation_events
from checkwash.frontends.python.parametrized_string_standins import parametrized_string_standin_events
from checkwash.shadow import _PYTEST_CONFIGS, find_runtime_subject_shadows
from checkwash.frontends.python.expected_provenance import importer_changes as expected_importer_changes, mark_expected_provenance
from checkwash.frontends.javascript.expected_provenance import mark_js_expected_provenance
from checkwash.gating import apply_gates, unit_is_live
from checkwash.arrival_collection import arrival_collector
from checkwash.ir.astutil import same_expr
from checkwash.ir.diffalign import align_file
from checkwash.ir.markers import parse_text
from checkwash.ir.model import IR, ChangeEvidence, DiffGlobals, Marker, judged_as_test, normalize_text
from checkwash.pyenv import known_baseline
from checkwash.report.context import ReportContext
from checkwash.roles import (
    _MAX_ORACLE_READS,
    _added_lines,
    _is_inert,
    _is_runner_script,
    _mentions_test_runner,
    _one_hop_runners,
    _runner_shape,
    _shell_shebang,
    _test_command_manifest,
    _test_commands_changed,
    collectable,
    is_artifact,
    is_test_support_path,
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

# SPEC section 2 resolves these roles before `test`, and a JS runner's default
# layout does not outrank them. Jest collects every file beneath `__tests__/`,
# but `__tests__/__snapshots__/out.js` is a stored expectation and
# `.claude/hooks/__tests__/guard.js` an agent constraint; making them only
# tests switched off EXPECTED_VALUE_CHANGED and GUARDRAIL_TOUCHED (#175
# review). Such a file keeps that public role and carries test obligations
# beside it: making it only that role switched off every test rule instead,
# so a weakened `.github/workflows/x.test.ts` passed at warn (#197). A
# collectable Python path does the same: `tests/golden/test_x.py` is a
# snapshot and is judged as a test beside it (#219).
_ROLES_BEFORE_TEST = frozenset({"guardrail", "ci", "snapshot", "lockfile", "conftest"})

# The conftest files a diff's test modules sit below, read from the head
# snapshot (#223). The stand-in context's limits: past them the run is an
# engine error, never a chain cut short.
_MAX_CHAIN_READS = 4096
_MAX_CHAIN_BYTES = 64_000_000


def _js_test(path: str, role: str, *sides: bytes | None) -> bool:
    """Does this JS/TS test file take the public role `test`?

    A path whose role resolved to one of `_ROLES_BEFORE_TEST` keeps that role
    and carries test obligations beside it instead (#197). The JS parse gate
    and rename expansion read `is_js_test_file` itself, which no role
    withdraws.
    """
    return role not in _ROLES_BEFORE_TEST and is_js_test_file(path, *sides)


def _scope_role(role: str, table_role: str, *sides: ParsedFile | None) -> str:
    """The role E7 judges an out-of-scope file by (#196 186.8).

    A test role read from the path alone gives way to the SPEC §2 table role
    unless the file declares a test on either side. With nothing to judge, no
    test rule reads the file, so its test role must not disarm E7 either.
    Every other rule keeps the test role, and no production credit comes back.
    """
    if role != table_role and not any(side is not None and side.declares_tests for side in sides):
        return table_role
    return role


def _innermost_focus(data: bytes, manifest):
    """Is this side's runner proven to run only the innermost focus? Asked
    only when the side holds focus, so the manifest stays unread otherwise
    (#196 187.2)."""
    return lambda: focus_is_innermost(runner_evidence(data, manifest))


def _base_root_file(changes: list[FileChange], root_reader, name: str,
                    set_aside: list[FileChange] | tuple[FileChange, ...] = ()):
    """A reader of one root file as the base side holds it.

    In the diff, its before side. Otherwise the head snapshot holds it
    unchanged, so that is the base side too (#196 186.7). Read once, and only
    when asked. A change set aside unread (#415) is in the diff as well: a
    readable before side is the base, and an unread one refuses, naming it,
    rather than taking the head bytes for the base.
    """
    read: list[bytes | None] = []

    def base() -> bytes | None:
        if not read:
            for change in (*changes, *set_aside):
                paths = (change.path.replace("\\", "/"), (change.old_path or "").replace("\\", "/"))
                if name in paths:
                    unread = _base_unread(change)
                    if unread is not None:
                        raise unread.refusal()
                    read.append(change.before)
                    break
            else:
                read.append(root_reader(name) if root_reader is not None else None)
        return read[0]

    return base


def _base_manifest(changes: list[FileChange], root_reader,
                   set_aside: list[FileChange] | tuple[FileChange, ...] = ()):
    """A reader of the base side's root package.json, for runner evidence,
    read only when a JS test file names no runner itself."""
    return _base_root_file(changes, root_reader, "package.json", set_aside)


def _base_unread(change: FileChange) -> UnreadSide | None:
    """The change's base side, when it was over the limit and not read (#415)."""
    if not change.unread or change.before is not None or change.status == "added":
        return None
    return next((side for side in change.unread if side.side == "base"), change.unread[0])


def _shebang_side(path: str, sides: tuple[bytes | None, ...],
                  unread: tuple[UnreadSide, ...]) -> UnreadSide | None:
    """The first unread side whose prefix gives `path` runner shape (#455).

    `_shell_shebang` reads only the first line within a side's first
    SHEBANG_PREFIX_BYTES bytes, and an unread side's prefix is those bytes,
    verified against the blob's object identity for a Git side. So a prefix
    answers exactly as the whole side would. The path exclusions are
    `_runner_shape`'s: a Python file, or a JS/TS test file judged on the
    readable sides, is never a runner by shape. A side whose prefix was not
    read answers nothing here.
    """
    if path.endswith(".py") or is_js_test_file(path, *sides):
        return None
    return next((side for side in unread if side.prefix is not None and _shell_shebang(side.prefix)), None)


def _detector_must_read(path: str, config: Config, change: FileChange,
                        scope_allow: list[str], listed_setup=None) -> bool:
    """Must a detector read this path's content (#415)?

    The runtime-provider pass reads every Python module the diff adds,
    deletes, renames or edits, whatever its role, because any of them can
    change which provider a test's import resolves to, and every pytest
    configuration at any depth for the search order it sets. It also reads
    a CI file, a file shaped like a runner script and a file with no dot in
    its name (for a shebang) as controls that can reorder that search, and
    the one-hop scan follows `./build/test.sh` from a changed script into
    whatever it names. None of these skips generated output, so neither does
    this. A runner-shaped file can be promoted to CI by what it says, which
    an unread side does not show. A shell shebang on an unread side is read
    from the side's prefix (#455), so it gives runner shape whatever the
    path's suffix, as it would at any size, and a shebang is the only shape
    a file with no extension has: such a file refuses only when a side's
    prefix was not read. Collection reads any file under the root
    `scripts/` directory, unless generated, for the pytest runs a root
    config governs (#196 184.3).

    Past those, generated output is skipped whatever its role. The test
    rules parse JS/TS test files, the guardrail rules read their files, a
    manifest naming the test command is promoted to CI by what it says, and
    EXPECTED_VALUE_CHANGED and SCOPE_DRIFT bind a stored expectation or an
    out-of-scope file to the digests of its content. A JS setup file the
    runner loads before every test file is read for the stand-ins it
    installs (#218): a named one, or one the base side's root package.json
    lists (`listed_setup` reads those, only when asked). Everything else
    (images, data, lockfiles, documentation, non-Python production sources)
    feeds only repair evidence, which an unread side never earns.
    """
    base = path.rsplit("/", 1)[-1]
    if path.endswith(".py") or base in _PYTEST_CONFIGS:
        return True
    sides = (change.before, change.after)
    role = config.role_of(path)
    if (role == "ci" or _runner_shape(path, *sides) or _shebang_side(path, sides, change.unread) is not None
            or _collection_runner(path)):
        return True
    # A shell shebang is the only runner shape an extensionless file has
    # (`scripts/test`, THREATMODEL 62). Each unread side's prefix answers
    # that question as the whole side would, so the file is judged like any
    # other unread path; only a side whose prefix was not read (a Git side
    # over the stream ceiling) still hides a shebang, and refuses (#455).
    if "." not in base.lstrip(".") and any(side.prefix is None for side in change.unread):
        return True
    if is_artifact(path):
        return False
    if role in ("guardrail", "snapshot"):
        return True
    if is_js_test_path(path) or may_be_evidenced_test_path(path):
        return True
    if _test_command_manifest(path) is not None:
        return True
    if is_carrier(path, frozenset()):
        return True
    if listed_setup is not None and path.endswith(_JS_EXTENSIONS) and is_carrier(path, listed_setup()):
        return True
    return bool(scope_allow) and not any(_scope_match(path, glob) for glob in scope_allow)


def _set_aside_unread(changes: list[FileChange], config: Config, scope_allow: list[str],
                      root_reader=None) -> tuple[list[FileChange], list[FileChange]]:
    """(readable changes, changes carried unread) (#415).

    A change with a side over the source byte limit holds no bytes for that
    side. If a detector must read either of its paths, the run refuses,
    naming path, side, size and limit; a side whose prefix holds the shell
    shebang is the side named (#455). Otherwise the whole change is set
    aside before any pass: no detector reads it and it earns no repair
    evidence, neither as an opaque change nor as changed symbols (#419). An
    unread side's prefix only ever answers the shebang question.

    The setup files the base package.json lists are asked last: package.json
    must be read itself, so by then it is readable in the diff or unchanged.
    """
    readable = [change for change in changes if not change.unread]
    unread = [change for change in changes if change.unread]

    def paths(change: FileChange) -> list[str]:
        return sorted({change.path.replace("\\", "/"), (change.old_path or change.path).replace("\\", "/")})

    for change in unread:
        if any(_detector_must_read(path, config, change, scope_allow) for path in paths(change)):
            raise _refused_side(change, paths(change)).refusal()
    listed: list[frozenset[str]] = []

    def listed_setup() -> frozenset[str]:
        if not listed:
            listed.append(listed_setup_files(_base_manifest(readable, root_reader)()))
        return listed[0]

    for change in unread:
        if any(_detector_must_read(path, config, change, scope_allow, listed_setup) for path in paths(change)):
            raise _refused_side(change, paths(change)).refusal()
    return readable, unread


def _set_aside_links(changes: list[FileChange], config: Config, scope_allow: list[str],
                     root_reader=None, root_path_lister=None,
                     root_batch_reader=None) -> tuple[list[FileChange], list[FileChange]]:
    """(the other changes, a virtual environment's own links set aside) (D-208).

    A working-tree run carries an untracked link in a virtual environment's
    `bin` or `Scripts` directory, or its `lib64`, with no bytes on either
    side, since nothing follows a link (`gitio.git._environment_links`). If
    a detector must read its path, by the rule a side over the source byte
    limit meets (#415) together with test, conftest and test-support paths, or
    if pytest's collection can enter the environment (`testpaths`, `addopts`,
    runner targets or `--collect-in-virtualenv`), the run refuses, naming it.
    Otherwise it is set aside before any pass: no detector reads it and it
    earns no repair evidence. The rule's question of a shell shebang on a side
    whose prefix was not read (#455) asks nothing of such a link: a link holds
    no bytes checkwash reads, and an untracked link reaches no commit, so no
    required check runs it.

    The setup files the base package.json lists are asked after the first
    pass, as in `_set_aside_unread`.
    """
    readable = [change for change in changes if not change.links]
    linked = [change for change in changes if change.links]
    if not linked:
        return readable, linked

    def _link_must_read(change: FileChange, listed_setup=None) -> bool:
        path = change.path.replace("\\", "/")
        if path.lower().endswith(".py") or _detector_must_read(path, config, change, scope_allow, listed_setup):
            return True
        if is_artifact(path):
            return False
        return config.role_of(path) in ("test", "conftest") or is_test_support_path(path)

    def refuse_must_read(listed_setup=None) -> None:
        for change in linked:
            if _link_must_read(change, listed_setup):
                raise change.links[0].refusal()

    refuse_must_read()
    listed: list[frozenset[str]] = []

    def listed_setup() -> frozenset[str]:
        if not listed:
            listed.append(listed_setup_files(_base_manifest(readable, root_reader)()))
        return listed[0]

    refuse_must_read(listed_setup)
    head_sources: dict[str, bytes] = {}
    if root_path_lister is not None and (root_batch_reader is not None or root_reader is not None):
        files, _opaque = split_inventory(root_path_lister())
        wanted = collection_sources(path for path in files if isinstance(path, str))
        fetched = root_batch_reader(wanted) if root_batch_reader is not None else {
            path: root_reader(path) for path in wanted
        }
        head_sources = {path: data for path, data in fetched.items() if isinstance(data, bytes)}
    elif root_reader is not None:
        head_sources = {
            path: data for path in sorted(_PYTEST_CONFIGS)
            if path in collection_sources((path,)) and isinstance(data := root_reader(path), bytes)
        }
    environments = sorted({link.environment for change in linked for link in change.links})
    reached = environment_reached(environments, head_sources, readable)
    if reached is not None:
        first = next(link for change in linked for link in change.links if link.environment == reached)
        raise first.refusal("pytest's collection can reach this environment")
    return readable, linked


def _refused_side(change: FileChange, paths: list[str]) -> UnreadSide:
    """The side a size refusal of `change` names (#415, #455).

    An unread side whose prefix holds a shell shebang that gives one of the
    change's paths runner shape, so the side that holds the shebang is
    named; otherwise the first unread side, as before.
    """
    sides = (change.before, change.after)
    for path in paths:
        side = _shebang_side(path, sides, change.unread)
        if side is not None:
            return side
    return change.unread[0]


def _shebang_free(unread_changes: list[FileChange]) -> frozenset[str]:
    """The paths of set-aside changes no side of which holds a shell shebang (#455).

    A readable side is known whole and an unread side by its prefix, which
    answers `_shell_shebang` as the whole side would; a side without a
    prefix is not known, so its change is left out. The runtime-provider
    pass skips such a path where it would read a dot-less path for a
    shebang: none is there, so the path holds no runner invocation on either
    side, and reading it would refuse, since its head bytes are not its base
    side.
    """
    free: set[str] = set()
    for change in unread_changes:
        if any(side.prefix is None or _shell_shebang(side.prefix) for side in change.unread):
            continue
        if _shell_shebang(change.before) or _shell_shebang(change.after):
            continue
        free.update(path.replace("\\", "/") for path in (change.path, change.old_path) if path)
    return frozenset(free)


def _guard_unread_reads(reader, unread_changes: list[FileChange], *, batch: bool = False):
    """`reader`, refusing a path set aside unread (#415).

    The readers serve the head snapshot for a path the diff does not hold,
    for both sides: a path absent from the changes is unchanged. A path set
    aside unread did change and has a side nobody read, so a reader that
    reaches for it refuses, naming that side, instead of handing over head
    bytes as the base side or bytes the limit kept out.
    """
    if reader is None or not unread_changes:
        return reader
    set_aside: dict[str, UnreadSide] = {}
    for change in unread_changes:
        for path in (change.path, change.old_path):
            if path:
                key = path.replace("\\", "/")
                named = [side for side in change.unread if side.path.replace("\\", "/") == key]
                set_aside.setdefault(key, (named or list(change.unread))[0])

    def refuse(path) -> None:
        if isinstance(path, str):
            side = set_aside.get(path.replace("\\", "/"))
            if side is not None:
                raise side.refusal()

    if batch:
        def read_many(paths):
            paths = list(paths)
            for path in paths:
                refuse(path)
            return reader(paths)
        return read_many

    def read(path, *args, **kwargs):
        refuse(path)
        return reader(path, *args, **kwargs)
    return read


def _change_evidence(change: FileChange, rename_destinations: dict[str, str]) -> ChangeEvidence:
    """Retain content identities only; canonicalize CRLF without erasing bytes."""
    return ChangeEvidence(
        before_sha256=(hashlib.sha256(change.before.replace(b"\r\n", b"\n")).hexdigest()
                       if change.before is not None else None),
        after_sha256=(hashlib.sha256(change.after.replace(b"\r\n", b"\n")).hexdigest()
                      if change.after is not None else None),
        old_path=change.old_path.replace("\\", "/") if change.old_path else None,
        rename_to=(rename_destinations.get(change.path.replace("\\", "/"))
                   if change.status == "deleted" else None),
    )


def _expand_renames(changes: list[FileChange], config: Config,
                    manifest: Callable[[], bytes | None] | None = None,
                    python_excludes: Callable[[str], bool] | None = None) -> list[FileChange]:
    """A rename that moves a test file out of collection is a disappearance.

    git's rename folding would otherwise analyse only the new path: `git mv
    tests/test_x.py attic/legacy.py` (R100) erased every unit from analysis
    with zero findings (confirmed red-team bypass). The added half is marked
    synthetic so relocated bytes don't count as a "non-trivial prod change"
    and defuse E1.

    pytest's default patterns judged a Python path alone, so `git mv
    test_app.py app_test.py` under `python_files = test_*.py` kept every unit
    aligned and silent while pytest stopped running them. A Python path the
    head's own configuration certainly leaves out, where it would collect the
    old path, has left collection too (`python_excludes`, D-193); an unknown
    configuration keeps the default reading.
    """
    expanded: list[FileChange] = []
    for change in changes:
        old = (change.old_path or "").replace("\\", "/")
        new = change.path.replace("\\", "/")
        if old and old != new:
            old_role = config.role_of(old)
            new_role = config.role_of(new)
            # Collection continuity ignores roles: a runner that collected
            # the old path collects the new one whatever role that path holds,
            # and the destination is judged as a test either way (#197 Q2).
            # A JS file's runner is the one its base side or the base
            # manifest proves; without that proof the rows form a union. The
            # runners match case-sensitively, so continuity does too (#196
            # 186.7, 186.3; `frontends/javascript/runners.py`).
            if is_js_test_file(old, change.before):
                old_test = True
                new_test = collection_continues(old, new, runner_evidence(change.before, manifest))
            else:
                # A Python test file is a collectable one, whatever its role
                # (219.Q1): pytest still collects `tests/golden/test_x.py`.
                old_test = collectable(old)
                new_test = is_js_test_file(new, change.after) or collectable(new)
                if (old_test and new_test and python_excludes is not None and not is_js_test_file(new, change.after)
                        and python_excludes(new) and not python_excludes(old)):
                    new_test = False
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
        tree = parse_text(seg, mode="eval")
        if tree is None:
            continue
        try:
            if isinstance(tree, ast.Expression) and isinstance(tree.body, ast.BinOp):
                out[name] = _binding_key(tree.body)
            else:
                out[name] = ast.unparse(tree)
        except ValueError:
            continue
    return out


def _native_assertion_context(
    data: bytes | None, parsed: ParsedFile | None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Exact surrounding source, with proven native bare-assert spans cut out.

    A raises/with assertion may span executable setup code; inherited asserts
    can point into a helper. Neither is safe to mask. Unknown/overlapping spans
    decline the proof rather than guessing where assertion code ends.
    """
    if data is None or parsed is None or not parsed.parse_ok:
        return None
    source = normalize_source(data)
    spans = []
    for unit in parsed.units:
        for assertion in unit.side.assertions:
            text = assertion.text
            if assertion.inherited or not (
                text.startswith("assert") and len(text) > 6
                and (text[6].isspace() or text[6] == "(")
            ):
                continue
            if (
                not isinstance(assertion.span, tuple) or len(assertion.span) != 2
                or any(type(value) is not int for value in assertion.span)
            ):
                return None
            start, end = assertion.span
            if not 0 <= start < end <= len(source) or source[start:end] != text:
                return None
            spans.append((start, end))
    if not spans:
        return None
    parts = []
    assertions = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            return None
        parts.append(source[cursor:start])
        assertions.append(source[start:end])
        cursor = end
    parts.append(source[cursor:])
    return tuple(parts), tuple(assertions)


def _root_importer_changes(changes, config, head_reader, head_searcher, path_lister=None):
    """Read unchanged callers of changed root helpers, once and within caps.

    A file absent from the real diff has the same bytes on both snapshots.
    Its inherited oracle can still change when a root helper changes. The
    existing snapshot search/reader APIs supply data; no repository code runs.
    Unlike a missing refactor credit, an incomplete reverse search could miss
    a removed oracle, so unavailable/exhausted discovery is an engine error.
    """
    modules = {}
    real_paths = {p.replace("\\", "/") for c in changes for p in (c.path, c.old_path) if p}
    for change in changes:
        path = change.path.replace("\\", "/")
        old_path = (change.old_path or "").replace("\\", "/")
        if (old_path and old_path != path and "/" not in old_path and old_path.endswith(".py")
                and change.before is not None and config.role_of(old_path) in ("test", "conftest")
                and transparent_root_helpers(change.before)):
            raise EngineError("root assertion helper renames are outside bounded importer analysis")
        if ("/" in path or not path.endswith(".py") or not path[:-3].isidentifier() or change.before is None
                or change.before == change.after or config.role_of(path) not in ("test", "conftest")):
            continue
        names = transparent_root_helpers(change.before)
        if names:
            modules[path[:-3]] = set(names)
    if not modules:
        return [], 0, set()
    if head_reader is None or head_searcher is None:
        raise EngineError("changed root assertion helpers require snapshot importer search")
    if len(modules) > _MAX_ORACLE_READS:
        raise EngineError("root assertion helper search exceeds the module budget")
    # The search reads no submodule; an importer inside one pytest can collect
    # is unknown (#335).
    if path_lister is not None:
        paths, opaque = split_inventory(path_lister())
        if opaque:
            sources = {path: head_reader(path) for path in collection_sources(
                path for path in paths if isinstance(path, str))}
            reached = opaque_reached(opaque, {p: s for p, s in sources.items() if isinstance(s, bytes)}, changes)
            if reached is not None:
                raise opaque_error(reached, "pytest's collection can reach it")
    candidates = sorted({p.replace("\\", "/") for p in head_searcher(sorted(modules))})
    # The existing grep returns at most 64 hits. Exactly 64 can be a truncated
    # set; never call that a complete review of removed helper assertions.
    if len(candidates) >= 64:
        raise EngineError("root assertion helper importer search may be truncated")
    discovered = []
    reads = 0
    for candidate in candidates:
        path = candidate.replace("\\", "/")
        # An importer is a test module pytest collects, whatever role its path
        # holds: `tests/golden/test_x.py` is one (#219, ruling 219.Q1).
        if (path in real_paths or not path.endswith(".py") or is_artifact(path)
                or not collectable(path)):
            continue
        if path.startswith("/") or ":" in path or any(p in ("", ".", "..") for p in path.split("/")):
            raise EngineError("root assertion helper search returned an invalid repository path")
        if reads >= min(_MAX_DUP_READS, _MAX_ORACLE_READS):
            raise EngineError("root assertion helper importer search exceeds the read budget")
        data = head_reader(path)
        reads += 1
        if data is None:
            raise EngineError(f"root assertion helper importer snapshot is unavailable: {path}")
        try:
            imports = root_imports(data)
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            continue
        if any(module in modules and original in modules[module] for module, original in imports.values()):
            discovered.append(FileChange(path=path, status="modified", before=data, after=data,
                                         synthetic="root_helper_importer"))
    return discovered, reads, set(modules)


from checkwash.engine_ir_credits import (
    RelocationContextResolver as _RelocationContextResolver,
    record_duplicate_survivors as _record_duplicate_survivors,
    record_move_credits as _record_move_credits,
)
from checkwash.engine_ir_files import populate_files_and_globals as _populate_files_and_globals
from checkwash.engine_ir_intake import (
    initialize_global_surface as _initialize_global_surface,
    prepare_diff_intake as _prepare_diff_intake,
)
from checkwash.engine_ir_postpass import (
    attach_config_report_evidence as _attach_config_report_evidence,
    mark_equivalence_and_provenance as _mark_equivalence_and_provenance,
    record_standin_installations as _record_standin_installations,
)
from checkwash.engine_ir_resolvers import (
    ConftestChainResolver as _ConftestChainResolver,
    CrossfileOracleResolver as _CrossfileOracleResolver,
    HeadCollectionResolver as _HeadCollectionResolver,
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
    report_context: ReportContext | None = None,
    root_reader=None,
    root_searcher=None,
    root_path_lister=None,
    root_batch_reader=None,
    pytest_configs=None,
    policy_base=None,
) -> IR:
    intake = _prepare_diff_intake(
        changes, config, scope_allow, head_reader=head_reader, report_context=report_context,
        root_reader=root_reader, root_searcher=root_searcher,
        root_path_lister=root_path_lister, root_batch_reader=root_batch_reader,
    )
    surface = _initialize_global_surface(
        intake, config, base_label=base_label, head_label=head_label,
        scope_allow=scope_allow, known_modules=known_modules, self_modules=self_modules,
        pytest_configs=pytest_configs, root_path_lister=root_path_lister,
    )
    chain_resolver = _ConftestChainResolver(
        intake.changes, config, intake.root_reader, report_context,
    )
    oracle_resolver = _CrossfileOracleResolver(
        surface.raw_by_path, config, intake.root_reader, intake.head_reader,
        report_context, intake.importer_reads, intake.reviewed_root_modules,
    )
    head_collection = _HeadCollectionResolver(
        intake.changes, chain_resolver.chain_sources, intake.root_reader,
        intake.root_batch_reader, root_path_lister, surface.config_evidence,
    )
    file_pass = _populate_files_and_globals(
        surface, intake, config, chain_resolver=chain_resolver,
        oracle_resolver=oracle_resolver, head_collection=head_collection,
        root_searcher=root_searcher, report_context=report_context, policy_base=policy_base,
    )
    relocation = _RelocationContextResolver(
        intake.changes, file_pass.expanded_changes, chain_resolver=chain_resolver,
        root_reader=intake.root_reader, root_searcher=root_searcher,
        root_path_lister=root_path_lister, report_context=report_context,
    )
    relocation.mark_ir_file_contexts(surface.ir)
    _record_move_credits(
        surface.ir, file_pass.js_head_runners, head_collection, relocation.relocation_sources,
    )
    _record_duplicate_survivors(
        surface.ir, head_searcher=head_searcher, head_reader=intake.head_reader,
        chain_resolver=chain_resolver, after_by_path=file_pass.after_by_path,
        relocation_resolver=relocation, head_collection=head_collection,
    )
    _record_standin_installations(
        surface.ir, intake.changes, intake.unread_changes, config,
        root_reader=intake.root_reader, root_searcher=root_searcher,
        root_path_lister=root_path_lister,
    )
    _mark_equivalence_and_provenance(
        surface.ir, surface.raw_by_path, intake.root_reader, root_searcher,
        config, report_context, oracle_resolver.strict_head_sources(),
    )
    _attach_config_report_evidence(
        surface.ir, surface.config_report_changes, surface.rename_destinations,
    )
    return surface.ir


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
    report_context: ReportContext | None = None,
    root_reader=None,
    root_searcher=None,
    root_path_lister=None,
    root_batch_reader=None,
    pytest_configs=None,
    policy_base=None,
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
        report_context=report_context,
        root_reader=root_reader,
        root_searcher=root_searcher,
        root_path_lister=root_path_lister,
        root_batch_reader=root_batch_reader,
        pytest_configs=pytest_configs,
        policy_base=policy_base,
    )
    findings = run_detectors(ir, config)
    verdict = apply_gates(ir, findings, contract, config, allow_entries, today)
    return ir, findings, verdict
