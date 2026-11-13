"""Pytest config & conftest sys.path controls, diff relevance gating, and SearchPlan resolution."""

from __future__ import annotations

import ast
import configparser
import posixpath
import re
import tomllib
from collections.abc import Mapping as _MappingABC
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping, Sequence

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.roles import _runner_shape, collectable
from checkwash.shadow_models import (
    HeadSearchResult,
    SearchPlan,
    _PYTEST_CONFIGS,
    _RunnerInvocation,
    _decode,
    _dedupe_roots,
    _dotted,
    _join,
    _live_shadow_attr,
    _normalise_root,
    _split_path_value,
)
from checkwash.shadow_providers import _extends_package_path
from checkwash.shadow_runners import (
    _align_runner_invocations,
    _could_be_extensionless_runner,
    _expand_invocation_targets,
    _invocation_applies,
    _runner_control,
    _runner_invocation_sides,
    _runner_invocations_live,
    _scope_applies,
)


def _import_mode(addopts: object) -> str:
    if isinstance(addopts, (list, tuple)):
        addopts = " ".join(str(value) for value in addopts)
    if not isinstance(addopts, str):
        return "prepend"
    matches = re.findall(
        r"(?:^|\s)--import-mode(?:=|\s+)(prepend|append|importlib)(?=\s|$)",
        addopts,
    )
    # argparse keeps the last occurrence, so config parsing must do the same.
    return matches[-1] if matches else "prepend"


def _config_search(path: str, data: bytes | None) -> tuple[tuple[str, ...], str]:
    """Return pytest ``pythonpath`` entries and import mode, in declared order."""

    base = path.rpartition("/")[0]
    filename = path.rsplit("/", 1)[-1]
    if filename in ("pyproject.toml", "pytest.toml", ".pytest.toml"):
        try:
            raw = tomllib.loads(_decode(data))
        except tomllib.TOMLDecodeError:
            return (), "prepend"
        if filename == "pyproject.toml":
            tool = raw.get("tool") if isinstance(raw.get("tool"), dict) else {}
            pytest_table = tool.get("pytest") if isinstance(tool, dict) else {}
            if not isinstance(pytest_table, dict):
                return (), "prepend"
            ini_options = pytest_table.get("ini_options")
            if isinstance(ini_options, dict):
                # Native `[tool.pytest]` is canonical in pytest 9 and wins
                # key-by-key when the legacy ini_options alias is also there.
                options = {
                    **ini_options,
                    **{
                        key: value
                        for key, value in pytest_table.items()
                        if key != "ini_options"
                    },
                }
            else:
                options = pytest_table
        else:
            options = raw.get("pytest")
        if not isinstance(options, dict):
            return (), "prepend"
        return _split_path_value(options.get("pythonpath"), base), _import_mode(
            options.get("addopts")
        )

    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read_string(_decode(data))
    except configparser.Error:
        return (), "prepend"
    sections = ("pytest", "tool:pytest")
    section = next((name for name in sections if parser.has_section(name)), None)
    if section is None:
        return (), "prepend"
    pythonpath = parser.get(section, "pythonpath", fallback="")
    addopts = parser.get(section, "addopts", fallback="")
    return _split_path_value(pythonpath, base), _import_mode(addopts)


def _path_expr(
    node: ast.AST,
    file_path: str,
    bindings: Mapping[str, str] | None = None,
) -> str | None:
    """Evaluate only deterministic repository-path expressions."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _normalise_root(node.value)
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return file_path
        return (bindings or {}).get(node.id)
    if isinstance(node, ast.Call):
        name = _dotted(node.func)
        if name in ("str", "Path", "pathlib.Path") and len(node.args) == 1:
            return _path_expr(node.args[0], file_path, bindings)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ("resolve", "absolute")
            and not node.args
        ):
            return _path_expr(node.func.value, file_path, bindings)
        if name in ("os.getcwd", "Path.cwd", "pathlib.Path.cwd") and not node.args:
            return ""
        if name in ("os.path.dirname", "posixpath.dirname") and len(node.args) == 1:
            value = _path_expr(node.args[0], file_path, bindings)
            return posixpath.dirname(value) if value is not None else None
        if name in ("os.path.abspath", "posixpath.abspath") and len(node.args) == 1:
            return _path_expr(node.args[0], file_path, bindings)
        if name in ("os.path.join", "posixpath.join") and node.args:
            values = [
                arg.value
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                else _path_expr(arg, file_path, bindings)
                for arg in node.args
            ]
            if any(value is None for value in values):
                return None
            return _normalise_root(posixpath.join(*(value or "" for value in values)))
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        value = _path_expr(node.value, file_path, bindings)
        return posixpath.dirname(value) if value else None
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, int)
        and node.slice.value >= 0
    ):
        value = _path_expr(node.value.value, file_path, bindings)
        if value is None:
            return None
        for _ in range(node.slice.value + 1):
            if not value:
                return None
            value = posixpath.dirname(value)
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_expr(node.left, file_path, bindings)
        right = (
            node.right.value
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
            else _path_expr(node.right, file_path, bindings)
        )
        if left is not None and right is not None:
            return _normalise_root(posixpath.join(left, right))
    return None


def _is_sys_path(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _sys_path_roots(path: str, data: bytes | None) -> tuple[str, ...]:
    """Literal roots prepended by a conftest, in final runtime order."""

    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return ()
    prepended: list[str] = []
    bindings: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = _path_expr(stmt.value, path, bindings) if stmt.value is not None else None
            for target in targets:
                if isinstance(target, ast.Name):
                    if value is None:
                        bindings.pop(target.id, None)
                    else:
                        bindings[target.id] = value
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "insert"
                and _is_sys_path(call.func.value)
                and len(call.args) >= 2
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == 0
            ):
                root = _path_expr(call.args[1], path, bindings)
                if root is not None:
                    prepended.insert(0, root)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            for target in targets:
                if not (
                    isinstance(target, ast.Subscript)
                    and _is_sys_path(target.value)
                    and isinstance(target.slice, ast.Slice)
                    and target.slice.upper is not None
                    and isinstance(target.slice.upper, ast.Constant)
                    and (
                        target.slice.lower is None
                        or (
                            isinstance(target.slice.lower, ast.Constant)
                            and target.slice.lower.value == 0
                        )
                    )
                    and target.slice.upper.value == 0
                    and isinstance(value, (ast.List, ast.Tuple))
                ):
                    continue
                roots: list[str] = []
                for elt in value.elts:
                    root = _path_expr(elt, path, bindings)
                    if root is not None:
                        roots.append(root)
                prepended[0:0] = roots
    return _dedupe_roots(prepended)


def _dormant_configs(config_paths: Iterable[str], paths: Iterable[str]) -> frozenset[str]:
    """Nested configs under a directory that holds no collected test (#346).

    Config discovery walks up from a test's directory, so such a config
    cannot be found for any test this pass analyses unless a run names it or
    starts discovery inside it. Root configs are never dormant.
    """

    test_dirs = {""}
    for path in paths:
        if collectable(path):
            parts = path.split("/")[:-1]
            test_dirs.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    return frozenset(
        path for path in config_paths if path.rpartition("/")[0] not in test_dirs
    )


class _LazyConfigSources(_MappingABC):
    """Config bytes looked up on first access, for config discovery (#346)."""

    def __init__(self, paths: Iterable[str], source: Callable[[str], bytes | None]):
        self._paths = tuple(sorted(set(paths)))
        self._known = frozenset(self._paths)
        self._source = source

    def __getitem__(self, path: str) -> bytes | None:
        if path not in self._known:
            raise KeyError(path)
        return self._source(path)

    def __iter__(self):
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)


def _pytest_config_matches(path: str, data: bytes | None) -> bool:
    """Whether pytest treats this filename's contents as a config."""

    filename = path.rsplit("/", 1)[-1]
    if filename in ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini"):
        return True
    if filename == "pyproject.toml":
        try:
            raw = tomllib.loads(_decode(data))
        except tomllib.TOMLDecodeError:
            return False
        tool = raw.get("tool") if isinstance(raw.get("tool"), dict) else {}
        return isinstance(tool.get("pytest"), dict) if isinstance(tool, dict) else False
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read_string(_decode(data))
    except configparser.Error:
        return False
    if filename == "tox.ini":
        return parser.has_section("pytest")
    if filename == "setup.cfg":
        return parser.has_section("tool:pytest")
    return False


def _pytest_config_path(
    paths: Iterable[str],
    test_path: str,
    targets: Sequence[str] = (),
    explicit: str | None = None,
    contents: Mapping[str, bytes | None] | None = None,
    cwd: str | None = None,
) -> str | None:
    """The single config pytest discovers for one invocation.

    Discovery starts at the invocation targets' common ancestor, not once per
    collected test.  That distinction prevents a nested config under
    ``tests/a`` from governing ``pytest tests/a tests/b``.
    """

    path_set = set(paths)
    if explicit is not None:
        return explicit if explicit in path_set else None
    priority = {
        "pytest.toml": 0,
        ".pytest.toml": 1,
        "pytest.ini": 2,
        ".pytest.ini": 3,
        "pyproject.toml": 4,
        "tox.ini": 5,
        "setup.cfg": 6,
    }
    if targets:
        directories = [
            target.rpartition("/")[0] if target.endswith(".py") else target.rstrip("/")
            for target in targets
        ]
        try:
            current = posixpath.commonpath(directories)
        except ValueError:
            current = ""
    elif cwd is not None:
        # An explicit targetless runner starts discovery at its process cwd.
        # It does not independently adopt a nested config for every collected
        # test. Parsed repository runners default to the repository root.
        current = cwd
    else:
        current = test_path.rpartition("/")[0]
    current = "" if current == "." else current.strip("/")
    fallback_pyproject: str | None = None
    while True:
        candidates = [
            _join(current, filename)
            for filename in priority
            if _join(current, filename) in path_set
        ]
        for candidate in sorted(
            candidates, key=lambda path: priority[path.rsplit("/", 1)[-1]]
        ):
            if _pytest_config_matches(
                candidate, (contents or {}).get(candidate)
            ):
                return candidate
            if (
                candidate.rsplit("/", 1)[-1] == "pyproject.toml"
                and fallback_pyproject is None
            ):
                # pytest 9 uses a pyproject without a pytest table only after
                # the normal search finds no qualifying configuration.
                fallback_pyproject = candidate
        if not current:
            return fallback_pyproject
        current = current.rpartition("/")[0]


def _pytest_import_root(test_path: str, paths: Iterable[str]) -> str:
    """Directory pytest prepends/appends for this test module.

    For a standalone test module it is the containing directory.  Inside a
    regular package pytest walks to the package root and inserts its parent;
    treating ``tests/`` as the root even when ``tests/__init__.py`` exists
    predicts a shadow Python never imports.
    """

    path_set = set(paths)
    directory = test_path.rpartition("/")[0]
    if not directory or f"{directory}/__init__.py" not in path_set:
        return directory
    current = directory
    while current and f"{current}/__init__.py" in path_set:
        current = current.rpartition("/")[0]
    return current


def _source_package(path: str, paths: Iterable[str]) -> str:
    """Package identity proved by this side's regular-package inventory.

    A standalone module has no relative import anchor. Package initializers
    participate even when empty; neither text search nor changed paths alone
    can prove this identity.
    """

    available = set(paths)
    directory = path.rpartition("/")[0]
    if not directory or f"{directory}/__init__.py" not in available:
        return ""
    root = _pytest_import_root(path, available)
    relative = directory[len(root) + 1 :] if root else directory
    pieces = relative.split("/")
    return ".".join(pieces) if all(p.isidentifier() for p in pieces) else ""


def _plan_roots(
    plan: SearchPlan, test_path: str, paths: Iterable[str], side: str
) -> tuple[str, ...]:
    roots = plan.before_roots if side == "before" else plan.after_roots
    mode = plan.before_mode if side == "before" else plan.after_mode
    test_dir = _pytest_import_root(test_path, paths)
    ordered: list[str | None] = list(roots)
    if mode == "prepend":
        ordered.insert(0, test_dir)
    ordered.append("")
    if mode == "append":
        ordered.append(test_dir)
    return _dedupe_roots(ordered)


def _is_conftest_path(path: str) -> bool:
    return path.rsplit("/", 1)[-1] == "conftest.py"


def _is_package_init(path: str) -> bool:
    return path == "__init__.py" or path.endswith("/__init__.py")


def _package_shape_change(path: str, change: FileChange) -> bool:
    """Did a regular/namespace/extended-package boundary change?"""

    old_path = (change.old_path or path).replace("\\", "/")
    old_init = _is_package_init(old_path)
    new_init = _is_package_init(path)
    if old_init != new_init or (old_init and old_path != path):
        return True
    if not old_init:
        return False
    if (change.before is None) != (change.after is None):
        return True
    return _extends_package_path(change.before) != _extends_package_path(change.after)


def _config_change(path: str, change: FileChange) -> bool:
    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    before_path = (change.old_path or path).replace("\\", "/")
    before_named = before_path.rsplit("/", 1)[-1] in configs
    after_named = path.rsplit("/", 1)[-1] in configs
    before_live = (
        before_named
        and change.before is not None
        and _pytest_config_matches(before_path, change.before)
    )
    after_live = (
        after_named
        and change.after is not None
        and _pytest_config_matches(path, change.after)
    )
    if before_live != after_live:
        return True
    if not before_live:
        return False
    if before_path != path:
        return True
    return _config_search(before_path, change.before) != _config_search(path, change.after)


def _search_order_change(path: str, change: FileChange, config: Config) -> bool:
    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    old_path = (change.old_path or path).replace("\\", "/")
    if (
        path.rsplit("/", 1)[-1] in configs
        or old_path.rsplit("/", 1)[-1] in configs
    ):
        return _config_change(path, change)
    if _is_conftest_path(path) or _is_conftest_path(old_path):
        before = _sys_path_roots(old_path, change.before) if _is_conftest_path(old_path) else ()
        after = _sys_path_roots(path, change.after) if _is_conftest_path(path) else ()
        return before != after
    # Python source cannot use any runner spelling understood below. This is
    # the overwhelmingly common path for ordinary source/test edits, so do
    # not route every file (and potentially every byte) through runner
    # classification just to learn that it is not a control.
    if path.endswith(".py") and old_path.endswith(".py"):
        return False
    if not (
        config.role_of(path) == "ci"
        or config.role_of(old_path) == "ci"
        or _runner_shape(path, change.before, change.after)
        or (
            old_path != path
            and _runner_shape(old_path, change.before, change.after)
        )
    ):
        return False
    return _runner_control(path, change, config)


def _relevant(changes: Sequence[FileChange], config: Config) -> bool:
    for change in changes:
        path = change.path.replace("\\", "/")
        old_path = (change.old_path or "").replace("\\", "/")
        provider_location_changed = (
            change.before is None
            or change.after is None
            or (old_path and old_path != path)
        )
        if provider_location_changed and (
            path.endswith(".py") or old_path.endswith(".py")
        ):
            return True
        if _search_order_change(path, change, config):
            return True
        if _package_shape_change(path, change):
            return True
    return False


@dataclass(frozen=True)
class _DiffGateState:
    """Validated relevance state and indexed diff/control maps for one call."""

    normally_relevant: bool
    provisional_staged_paths: set[str]
    change_by_path: dict[str, FileChange]
    control_changes: dict[str, FileChange]
    side_change_by_path: dict[str, FileChange]
    changed_control_paths: set[str]
    changed_config_paths: set[str]
    search_order_changed: bool


def _gate_shadow_diff(
    changes: Sequence[FileChange],
    config: Config,
    *,
    head_path_lister: Callable[[], Sequence[str]] | None,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
    head_searcher: Callable[[list[str]], Sequence[str] | HeadSearchResult] | None,
    config_evidence,
) -> _DiffGateState | None:
    """Gate relevance & lazy-path fast exits, then index changed paths and controls."""

    if (head_path_lister is None) != (head_batch_reader is None):
        raise EngineError("runtime-shadow inventory requires both path and byte readers")
    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    effective_configs = config_evidence.changes if config_evidence is not None else {}
    normally_relevant = _relevant(changes, config) or any(
        _config_change(path, change) for path, change in effective_configs.items()
    )
    can_inventory_staged = head_searcher is not None or (
        head_path_lister is not None and head_batch_reader is not None
    )
    if not normally_relevant and not can_inventory_staged:
        return None
    provisional_staged_paths = (
        {
            change.path.replace("\\", "/")
            for change in changes
            if change.path.replace("\\", "/").endswith(".py")
            and change.before is not None
            and change.after is not None
        }
        if can_inventory_staged
        else set()
    )
    if not normally_relevant and not provisional_staged_paths:
        return None

    change_by_path = {c.path.replace("\\", "/"): c for c in changes}
    control_changes = {**change_by_path, **effective_configs}
    side_change_by_path = dict(change_by_path)
    for change in changes:
        old_path = (change.old_path or "").replace("\\", "/")
        if old_path and old_path != change.path.replace("\\", "/"):
            side_change_by_path[old_path] = change
    changed_control_paths = {
        path
        for path, change in change_by_path.items()
        if _search_order_change(path, change, config)
    }
    changed_control_paths.update(
        path for path, change in effective_configs.items() if _config_change(path, change)
    )
    changed_config_paths = {
        path
        for path in changed_control_paths
        if path.rsplit("/", 1)[-1] in configs
        or (control_changes[path].old_path or path)
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        in configs
    }
    return _DiffGateState(
        normally_relevant=normally_relevant,
        provisional_staged_paths=provisional_staged_paths,
        change_by_path=change_by_path,
        control_changes=control_changes,
        side_change_by_path=side_change_by_path,
        changed_control_paths=changed_control_paths,
        changed_config_paths=changed_config_paths,
        search_order_changed=bool(changed_control_paths),
    )


@dataclass(frozen=True)
class _ControlInvocations:
    """Resolved conftest sys.path mutations and aligned runner invocations."""

    conftest_controls: list[tuple[str, tuple[str, ...], tuple[str, ...]]]
    runner_controls: list[tuple[str, _RunnerInvocation, _RunnerInvocation]]


def _collect_control_invocations(
    *,
    conftest_paths: Sequence[str],
    before_paths: set[str],
    after_paths: set[str],
    changed_runner_paths: Sequence[str],
    runner_snapshot_paths: Sequence[str],
    change_by_path: Mapping[str, FileChange],
    side_change_by_path: Mapping[str, FileChange],
    snapshot: Mapping[str, bytes | None],
    side_source: Callable[[str, str, Mapping[str, FileChange], Mapping[str, bytes | None]], bytes | None],
    config: Config,
) -> _ControlInvocations:
    """Extract conftest sys.path controls and aligned runner/CI invocations."""

    conftest_controls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for path in conftest_paths:
        before_sys = (
            _sys_path_roots(
                path, side_source(path, "before", side_change_by_path, snapshot)
            )
            if path in before_paths
            else ()
        )
        after_sys = (
            _sys_path_roots(
                path, side_source(path, "after", side_change_by_path, snapshot)
            )
            if path in after_paths
            else ()
        )
        if before_sys or after_sys:
            conftest_controls.append((path, before_sys, after_sys))

    runner_controls: list[tuple[str, _RunnerInvocation, _RunnerInvocation]] = []
    before_test_inventory = tuple(sorted(path for path in before_paths if collectable(path)))
    after_test_inventory = tuple(sorted(path for path in after_paths if collectable(path)))
    for path in changed_runner_paths:
        change = change_by_path[path]
        before_invocations, after_invocations = _runner_invocation_sides(path, change, config)
        before_expanded = tuple(
            expanded
            for invocation in before_invocations
            if (expanded := _expand_invocation_targets(invocation, before_test_inventory))
            is not None
        )
        after_expanded = tuple(
            expanded
            for invocation in after_invocations
            if (expanded := _expand_invocation_targets(invocation, after_test_inventory))
            is not None
        )
        runner_controls.extend(
            (path, before, after)
            for before, after in _align_runner_invocations(before_expanded, after_expanded)
        )
    for path in runner_snapshot_paths:
        if path in side_change_by_path:
            continue
        data = snapshot.get(path)
        for invocation in _runner_invocations_live(path, data, config):
            expanded = _expand_invocation_targets(invocation, after_test_inventory)
            if expanded is not None:
                runner_controls.append((path, expanded, expanded))
    return _ControlInvocations(
        conftest_controls=conftest_controls,
        runner_controls=runner_controls,
    )


def _resolve_test_conftest_roots(
    test_path: str,
    conftest_controls: Sequence[tuple[str, tuple[str, ...], tuple[str, ...]]],
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Fold parent-to-nested conftest sys.path prepends applicable to ``test_path``."""

    before_sys: tuple[str, ...] = ()
    after_sys: tuple[str, ...] = ()
    sys_trigger: str | None = None
    for path, before_roots, after_roots in sorted(
        conftest_controls,
        key=lambda item: (item[0].count("/"), item[0]),
    ):
        if not _scope_applies(path.rpartition("/")[0], test_path):
            continue
        before_sys = _dedupe_roots([*before_roots, *before_sys])
        after_sys = _dedupe_roots([*after_roots, *after_sys])
        if before_roots != after_roots:
            sys_trigger = path
    return before_sys, after_sys, sys_trigger


def _resolve_config_side(
    side: str,
    paths: set[str],
    test_path: str,
    invocation: _RunnerInvocation | None,
    config_source: Callable[[str, str], bytes | None],
) -> tuple[str | None, tuple[str, ...], str]:
    """Lazily discover pytest configuration and import mode for one side."""

    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    config_contents = _LazyConfigSources(
        (path for path in paths if path.rsplit("/", 1)[-1] in configs),
        lambda path: config_source(path, side),
    )
    cfg = _pytest_config_path(
        paths,
        test_path,
        invocation.targets if invocation is not None else (),
        invocation.config_path if invocation is not None else None,
        config_contents,
        invocation.cwd if invocation is not None else None,
    )
    roots, configured_mode = _config_search(
        cfg or "pytest.ini",
        config_source(cfg, side) if cfg else None,
    )
    mode = (
        invocation.mode
        if invocation is not None and invocation.mode is not None
        else configured_mode
    )
    return cfg, roots, mode


def _selected_changed_configs(
    before_cfg: str | None,
    after_cfg: str | None,
    control_changes: Mapping[str, FileChange],
) -> set[str]:
    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    return {
        path
        for path, change in control_changes.items()
        if (
            path.rsplit("/", 1)[-1] in configs
            or (change.old_path or path).replace("\\", "/").rsplit("/", 1)[-1] in configs
        )
        and _config_change(path, change)
        and (
            path == after_cfg
            or (change.old_path or path).replace("\\", "/") == before_cfg
        )
    }


def _build_test_search_plans(
    test_path: str,
    *,
    before_paths: set[str],
    after_paths: set[str],
    eligible_tests: set[str],
    controls_state: _ControlInvocations,
    control_changes: Mapping[str, FileChange],
    config_source: Callable[[str, str], bytes | None],
) -> list[SearchPlan]:
    """Construct deduplicated SearchPlan candidates governing ``test_path``."""

    before_sys, after_sys, sys_trigger = _resolve_test_conftest_roots(
        test_path, controls_state.conftest_controls
    )
    plans: list[SearchPlan] = []
    if controls_state.runner_controls:
        for runner_path, before_invocation, after_invocation in controls_state.runner_controls:
            if not (
                _invocation_applies(before_invocation, test_path)
                and _invocation_applies(after_invocation, test_path)
            ):
                continue
            before_cfg, before_cfg_roots, before_mode = _resolve_config_side(
                "before", before_paths, test_path, before_invocation, config_source
            )
            after_cfg, after_cfg_roots, after_mode = _resolve_config_side(
                "after", after_paths, test_path, after_invocation, config_source
            )
            controls = _selected_changed_configs(before_cfg, after_cfg, control_changes)
            trigger = sys_trigger or next(iter(sorted(controls)), runner_path)
            plans.append(
                SearchPlan(
                    trigger,
                    _dedupe_roots([*before_sys, *before_cfg_roots, *before_invocation.roots]),
                    _dedupe_roots([*after_sys, *after_cfg_roots, *after_invocation.roots]),
                    before_mode,
                    after_mode,
                    control_paths=tuple(sorted(controls)),
                )
            )
    else:
        implicit = _RunnerInvocation((), tuple(sorted(eligible_tests)))
        before_cfg, before_cfg_roots, before_mode = _resolve_config_side(
            "before", before_paths, test_path, implicit, config_source
        )
        after_cfg, after_cfg_roots, after_mode = _resolve_config_side(
            "after", after_paths, test_path, implicit, config_source
        )
        controls = _selected_changed_configs(before_cfg, after_cfg, control_changes)
        plans.append(
            SearchPlan(
                sys_trigger or next(iter(sorted(controls)), "pytest import path"),
                _dedupe_roots([*before_sys, *before_cfg_roots]),
                _dedupe_roots([*after_sys, *after_cfg_roots]),
                before_mode,
                after_mode,
                control_paths=tuple(sorted(controls)),
            )
        )

    unique_plans: dict[tuple[tuple[str, ...], tuple[str, ...], str, str], SearchPlan] = {}
    for plan in plans:
        key = (plan.before_roots, plan.after_roots, plan.before_mode, plan.after_mode)
        if key in unique_plans:
            existing = unique_plans[key]
            unique_plans[key] = replace(
                existing,
                control_paths=tuple(sorted({*existing.control_paths, *plan.control_paths})),
            )
        else:
            unique_plans[key] = plan
    return list(unique_plans.values())
