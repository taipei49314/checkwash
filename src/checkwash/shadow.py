"""Runtime import-provider shadow detection (#86 / #95).

This is deliberately an import-resolution check, not a filename rule.  A
candidate exists only when an existing test imported the same dotted module
on both sides, that module resolved to first-party production at base, and a
different, non-equivalent repository provider wins at head.  Package,
namespace-package and search-path spellings all feed the same predicate.

The repository snapshot is requested lazily.  A new provider, a search-path
edit, or a semantic edit to a provider that an existing test imports can open
the inventory path; ordinary edits with no usable inventory callbacks remain
on the fast path.  Names are listed once, candidate sources are fetched in two
bounded batches (tests/controls, then exact providers), and only collectable
test files are parsed.
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import posixpath
import re
import shlex
import tomllib
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.frontends.python.frontend import _static_truth, parse_python
from checkwash.roles import _is_runner_script, _runner_shape, _runs_tests, collectable


_PYTEST_CONFIGS = frozenset(
    {
        "pytest.toml",
        ".pytest.toml",
        "pytest.ini",
        ".pytest.ini",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
    }
)
_PYTHONPATH_REFS = frozenset(
    {"${pythonpath}", "$pythonpath", "%pythonpath%", "$env:pythonpath"}
)


@dataclass(frozen=True)
class SearchPlan:
    """One concrete way pytest can obtain its import search order."""

    trigger: str
    before_roots: tuple[str, ...]
    after_roots: tuple[str, ...]
    before_mode: str = "prepend"
    after_mode: str = "prepend"
    scope_dir: str = ""
    control_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RunnerInvocation:
    """Environment and CLI facts captured at one concrete pytest command."""

    roots: tuple[str, ...]
    targets: tuple[str, ...] = ()
    mode: str | None = None
    config_path: str | None = None
    # ``None`` is reserved for the detector's implicit, inventory-wide pytest
    # model.  A parsed runner has a concrete process cwd; absent contrary
    # evidence that is the repository root (``""``).
    cwd: str | None = None
    # Exact collectable tests proven to be selected after literal shell-glob
    # expansion against one side's inventory. ``None`` means not normalised.
    scope: tuple[str, ...] | None = None
    # Preserve the parsed selector before side-specific glob expansion.  The
    # exact same selector and cwd still identify one command when unrelated
    # tests make the two inventory-derived scopes differ.
    raw_targets: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SubjectShadow:
    finding_path: str
    module: str
    before_provider: str
    after_provider: str
    test_path: str
    trigger: str
    # Importing a module executes every regular package initializer in its
    # provider chain. Those files are part of the stand-in too, and therefore
    # cannot buy repair evidence for another oracle finding in the same diff.
    after_chain: tuple[str, ...] = ()
    # Findings deduplicate package fanout, but every suppressed sibling leaf
    # remains a stand-in and must still be excluded from repair evidence.
    related_evidence_paths: tuple[str, ...] = ()
    # A changed path that made this provider win is oracle plumbing, not a
    # production repair. This matters for supported controls whose frozen role
    # spelling is still `prod` (notably `.pytest.ini`).
    control_paths: tuple[str, ...] = ()
    reportable: bool = True


@dataclass(frozen=True)
class HeadSearchResult:
    """Paths returned by a snapshot search, with explicit completeness.

    A plain sequence remains a supported legacy result, but is deliberately
    treated as incomplete.  Only a frontend that traversed the complete head
    snapshot may attest completeness; a caller-provided cap must never become
    proof that no importing test exists.
    """

    paths: tuple[str, ...]
    complete: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))

    def __iter__(self):
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index):
        return self.paths[index]


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _normalise_root(value: str, base: str = "") -> str | None:
    value = value.strip().strip("\"'").replace("\\", "/")
    if value.lower() in _PYTHONPATH_REFS:
        return None
    for token in ("${PYTHONPATH}", "$PYTHONPATH", "%PYTHONPATH%", "$env:PYTHONPATH"):
        value = value.replace(token, "")
    value = value.replace("{toxinidir}", ".").replace("${PWD}", ".").replace("$PWD", ".")
    if not value or value == ".":
        value = ""
    if value.startswith(("/", "~/")) or re.match(r"^[A-Za-z]:/", value):
        return None  # only repository-relative providers are in the inventory
    joined = posixpath.join(base, value) if base and value else (base or value)
    norm = posixpath.normpath(joined or ".")
    if norm == ".":
        return ""
    if norm == ".." or norm.startswith("../"):
        return None
    return norm.strip("/")


def _dedupe_roots(values: Iterable[str | None]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if value is None or value in out:
            continue
        out.append(value)
    return tuple(out)


def _split_path_value(
    value: object,
    base: str = "",
    inherited: Iterable[str] = (),
) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value if isinstance(v, str)]
    elif isinstance(value, str):
        # POSIX shlex treats a backslash as an escape and would turn
        # ``.\shadow`` into ``.shadow``. Normalise path separators before
        # tokenisation so Windows-authored repository-relative roots survive.
        value = value.replace("\\", "/")
        try:
            raw = shlex.split(value.replace("\n", " "), posix=True)
        except ValueError:
            raw = value.replace("\n", " ").split()
    else:
        return ()
    parts: list[str] = []
    for item in raw:
        # Repository-relative PYTHONPATH values are deterministic across OS;
        # accept both separators so a Windows-authored runner is read the same
        # way on Linux.  Absolute drive paths were rejected above.
        for semicolon_part in item.split(";"):
            if semicolon_part.lower() in _PYTHONPATH_REFS:
                parts.extend(inherited)
                continue
            colon_parts = (
                [semicolon_part]
                if re.match(r"^[A-Za-z]:[\\/]", semicolon_part)
                else semicolon_part.split(":")
            )
            for part in colon_parts:
                if part.lower() in _PYTHONPATH_REFS:
                    parts.extend(inherited)
                    continue
                root = _normalise_root(part, base)
                if root is not None:
                    parts.append(root)
    return _dedupe_roots(parts)


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


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


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


_POWERSHELL_PYTHONPATH = re.compile(
    r"^\s*\$env:PYTHONPATH\s*=\s*([\"'])(.*?)\1\s*(?:#.*)?$",
    re.IGNORECASE,
)
_BATCH_PYTHONPATH = re.compile(
    r"^\s*set\s+(?:\"PYTHONPATH=(.*?)\"|PYTHONPATH\s*=\s*(.*?))\s*$",
    re.IGNORECASE,
)
_YAML_PYTHONPATH = re.compile(
    r"^\s*PYTHONPATH\s*:\s*([\"']?)(.*?)\1\s*(?:#.*)?$",
    re.IGNORECASE,
)


def _shell_pythonpath(line: str) -> tuple[str, bool] | None:
    """A literal shell assignment, optionally prefixing the test command."""

    try:
        words = shlex.split(line.replace("\\", "/"), comments=True, posix=True)
    except ValueError:
        return None
    exported = bool(words and words[0].lower() == "export")
    if exported:
        words = words[1:]
    if not words or "=" not in words[0]:
        return None
    name, value = words[0].split("=", 1)
    if name.lower() != "pythonpath":
        return None
    # Any prefix assignment with a following command is command-scoped.  It
    # must never become persistent merely because that command is `echo`
    # rather than pytest.
    command_scoped = not exported and len(words) > 1
    return value, command_scoped


_PYTEST_OPTIONS_WITH_VALUE = frozenset(
    {
        "-k",
        "-m",
        "-c",
        "--config-file",
        "--rootdir",
        "--confcutdir",
        "--basetemp",
        "--override-ini",
        "-o",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--junitxml",
        "--maxfail",
        "--durations",
        "--import-mode",
    }
)


def _line_words(line: str) -> list[str]:
    try:
        return shlex.split(line.replace("\\", "/"), comments=True, posix=True)
    except ValueError:
        return []


def _pytest_args(words: Sequence[str]) -> list[str] | None:
    """Arguments after an actual pytest command, never a textual mention."""

    cleaned = list(words)
    while cleaned and cleaned[0] in ("-", "run:", "command:"):
        cleaned.pop(0)
    if not cleaned:
        return None
    executable = posixpath.basename(cleaned[0]).lower()
    if executable in ("echo", "printf", "write-output", "rem", "::"):
        return None
    for index, word in enumerate(cleaned):
        base = posixpath.basename(word).lower()
        if base in ("pytest", "pytest.exe", "py.test", "py.test.exe"):
            return cleaned[index + 1 :]
        if (
            (base.startswith("python") or base in ("py", "pypy", "pypy3"))
            and index + 2 < len(cleaned)
            and cleaned[index + 1] == "-m"
            and cleaned[index + 2] == "pytest"
        ):
            return cleaned[index + 3 :]
    return None


def _pytest_cli(args: Sequence[str]) -> tuple[tuple[str, ...], str | None, str | None]:
    targets: list[str] = []
    mode: str | None = None
    config_path: str | None = None
    skip_value = False
    for index, argument in enumerate(args):
        if skip_value:
            skip_value = False
            continue
        if argument.startswith("--import-mode="):
            candidate = argument.split("=", 1)[1]
            if candidate in ("prepend", "append", "importlib"):
                mode = candidate
            continue
        if argument == "--import-mode" and index + 1 < len(args):
            candidate = args[index + 1]
            if candidate in ("prepend", "append", "importlib"):
                mode = candidate
            skip_value = True
            continue
        if argument in ("-c", "--config-file") and index + 1 < len(args):
            config_path = _normalise_root(args[index + 1])
            skip_value = True
            continue
        if argument.startswith("--config-file="):
            config_path = _normalise_root(argument.split("=", 1)[1])
            continue
        if argument in _PYTEST_OPTIONS_WITH_VALUE:
            skip_value = True
            continue
        if argument.startswith("-") or argument in ("&&", "||", ";", "|"):
            continue
        target = argument.split("::", 1)[0]
        normalised = _normalise_root(target)
        if normalised in (None, ""):
            # `pytest .` is an unscoped repository invocation.
            if normalised == "":
                targets.clear()
                break
            continue
        targets.append(normalised)
    return _dedupe_roots(targets), mode, config_path


def _runner_invocations(path: str, data: bytes | None) -> tuple[_RunnerInvocation, ...]:
    if not data or not _runs_tests(data):
        return ()
    persistent: tuple[str, ...] = ()
    invoked: list[_RunnerInvocation] = []
    yaml_environment: tuple[str, ...] | None = None
    for line in _decode(data).split("\n"):
        words = _line_words(line)
        shell = _shell_pythonpath(line)
        if shell is not None:
            value, command_scoped = shell
            roots = _split_path_value(value, inherited=persistent)
            if command_scoped:
                args = _pytest_args(words[1:])
                if args is not None:
                    targets, mode, config_path = _pytest_cli(args)
                    invoked.append(
                        _RunnerInvocation(roots, targets, mode, config_path, "")
                    )
            else:
                persistent = roots
            continue
        powershell = _POWERSHELL_PYTHONPATH.match(line)
        if powershell:
            persistent = _split_path_value(
                powershell.group(2), inherited=persistent
            )
            continue
        batch = _BATCH_PYTHONPATH.match(line)
        if batch:
            persistent = _split_path_value(
                batch.group(1) if batch.group(1) is not None else batch.group(2),
                inherited=persistent,
            )
            continue
        yaml = _YAML_PYTHONPATH.match(line)
        if yaml:
            yaml_environment = _split_path_value(
                yaml.group(2), inherited=persistent
            )
            persistent = yaml_environment
            continue
        args = _pytest_args(words)
        if args is not None:
            targets, mode, config_path = _pytest_cli(args)
            invoked.append(
                _RunnerInvocation(persistent, targets, mode, config_path, "")
            )
    # A YAML env mapping is structural rather than shell execution order; its
    # line may appear after the run key while still governing that step.
    if yaml_environment is not None:
        invoked = [replace(item, roots=yaml_environment) for item in invoked]
    return tuple(invoked)


def _runner_pythonpath(path: str, data: bytes | None) -> tuple[str, ...]:
    """Compatibility view: roots at the last actual pytest invocation."""

    invocations = _runner_invocations(path, data)
    return invocations[-1].roots if invocations else ()


def _import_targets(node: ast.AST, extra_used: Iterable[str] = ()) -> set[str]:
    Position = tuple[int, int]
    bindings: list[tuple[str, tuple[str, ...], Position]] = []
    external_used = set(extra_used)
    loads: dict[str, list[Position]] = {}
    writes: dict[str, list[Position]] = {}

    def position(current: ast.AST) -> Position:
        return getattr(current, "lineno", -1), getattr(current, "col_offset", -1)

    def write(name: str, current: ast.AST) -> None:
        writes.setdefault(name, []).append(position(current))

    def bind(target: ast.AST | None, current: ast.AST) -> None:
        if isinstance(target, ast.Name):
            write(target.id, current)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, current)
        elif isinstance(target, ast.Starred):
            bind(target.value, current)

    class Visitor(ast.NodeVisitor):
        def __init__(self, root: ast.AST):
            self.root = root

        def visit_FunctionDef(self, current):  # noqa: N802 - ast visitor API
            if current is self.root:
                self.generic_visit(current)
            else:
                write(current.name, current)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, current):  # noqa: N802 - ast visitor API
            if current is self.root:
                self.generic_visit(current)
            else:
                write(current.name, current)

        def visit_Lambda(self, current):  # noqa: N802 - ast visitor API
            return

        def visit_If(self, current):  # noqa: N802 - ast visitor API
            # Imports used only for typing never become runtime providers.
            guard = _dotted(current.test)
            if guard in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
                for stmt in current.orelse:
                    self.visit(stmt)
                return
            truth = _static_truth(current.test)
            if truth is not None:
                branch = current.body if truth else current.orelse
                for stmt in branch:
                    self.visit(stmt)
                return
            self.generic_visit(current)

        def visit_Import(self, current):  # noqa: N802 - ast visitor API
            for alias in current.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                write(local, current)
                bindings.append((local, (alias.name,), position(current)))

        def visit_ImportFrom(self, current):  # noqa: N802 - ast visitor API
            if current.level or not current.module:
                return
            for alias in current.names:
                if alias.name != "*":
                    local = alias.asname or alias.name
                    write(local, current)
                    bindings.append(
                        (
                            local,
                            (current.module, f"{current.module}.{alias.name}"),
                            position(current),
                        )
                    )

        def visit_Assign(self, current):  # noqa: N802 - ast visitor API
            for target in current.targets:
                bind(target, current)
            self.visit(current.value)

        def visit_AnnAssign(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            if current.value is not None:
                self.visit(current.value)

        def visit_AugAssign(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.visit(current.value)

        def visit_NamedExpr(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.visit(current.value)

        def visit_For(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.generic_visit(current)

        visit_AsyncFor = visit_For

        def visit_With(self, current):  # noqa: N802 - ast visitor API
            for item in current.items:
                bind(item.optional_vars, current)
            self.generic_visit(current)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, current):  # noqa: N802 - ast visitor API
            if current.name:
                write(current.name, current)
            self.generic_visit(current)

        def visit_Delete(self, current):  # noqa: N802 - ast visitor API
            for target in current.targets:
                bind(target, current)

        def visit_Name(self, current):  # noqa: N802 - ast visitor API
            if isinstance(current.ctx, ast.Load):
                loads.setdefault(current.id, []).append(position(current))

    Visitor(node).visit(node)

    def reaches_use(local: str, imported_at: Position) -> bool:
        later_writes = [
            written_at
            for written_at in writes.get(local, ())
            if written_at > imported_at
        ]
        if local in external_used and not later_writes:
            return True
        return any(
            loaded_at > imported_at
            and not any(imported_at < written_at < loaded_at for written_at in later_writes)
            for loaded_at in loads.get(local, ())
        )

    return {
        target
        for local, targets, imported_at in bindings
        if reaches_use(local, imported_at)
        for target in targets
    }


def _scope_global_loads(scope: ast.AST) -> set[str]:
    """Names a function reads from module scope, excluding local bindings."""

    class Names(ast.NodeVisitor):
        def __init__(self):
            self.loads: set[str] = set()
            self.locals: set[str] = set()
            self.globals: set[str] = set()

        def visit_FunctionDef(self, current):  # noqa: N802
            if current is scope:
                self.generic_visit(current)
            else:
                self.locals.add(current.name)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, current):  # noqa: N802
            if current is scope:
                self.generic_visit(current)
            else:
                self.locals.add(current.name)

        def visit_Global(self, current):  # noqa: N802
            self.globals.update(current.names)

        def visit_Nonlocal(self, current):  # noqa: N802
            self.locals.update(current.names)

        def visit_arg(self, current):  # noqa: N802
            self.locals.add(current.arg)

        def visit_Import(self, current):  # noqa: N802
            self.locals.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in current.names
            )

        def visit_ImportFrom(self, current):  # noqa: N802
            self.locals.update(
                alias.asname or alias.name
                for alias in current.names
                if alias.name != "*"
            )

        def visit_Name(self, current):  # noqa: N802
            if isinstance(current.ctx, ast.Load):
                self.loads.add(current.id)
            else:
                self.locals.add(current.id)

    names = Names()
    names.visit(scope)
    return names.loads - (names.locals - names.globals)


@dataclass(frozen=True)
class _FixtureBinding:
    imports: frozenset[str]
    dependencies: frozenset[str]
    autouse: bool = False


def _fixture_decorator(node: ast.AST) -> ast.AST | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    return next(
        (
            decorator
            for decorator in node.decorator_list
            if _dotted(decorator.func if isinstance(decorator, ast.Call) else decorator)
            in ("pytest.fixture", "fixture")
        ),
        None,
    )


def _fixture_bindings(data: bytes | None) -> dict[str, _FixtureBinding]:
    """Top-level fixtures and only the imports their bodies actually use."""

    if not data:
        return {}
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return {}
    module = ast.Module(body=list(tree.body), type_ignores=[])
    out: dict[str, _FixtureBinding] = {}
    for node in tree.body:
        decorator = _fixture_decorator(node)
        if decorator is None:
            continue
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        name = node.name
        autouse = False
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    name = keyword.value.value
                elif (
                    keyword.arg == "autouse"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    autouse = True
        imports = _import_targets(node) | _import_targets(
            module, _scope_global_loads(node)
        )
        dependencies = {
            argument.arg
            for argument in (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )
            if argument.arg not in ("self", "cls")
        }
        out[name] = _FixtureBinding(
            imports=frozenset(imports),
            dependencies=frozenset(dependencies),
            autouse=autouse,
        )
    return out


def _pytest_mark_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Local names that provably denote ``pytest`` or ``pytest.mark``."""

    pytest_names: set[str] = set()
    mark_names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name == "pytest":
                    pytest_names.add(alias.asname or "pytest")
        elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module == "pytest":
            for alias in stmt.names:
                if alias.name == "mark":
                    mark_names.add(alias.asname or "mark")
    return pytest_names, mark_names


def _pytest_mark_kind(
    decorator: ast.AST,
    aliases: tuple[set[str], set[str]],
) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = _dotted(target)
    pytest_names, mark_names = aliases
    for name in pytest_names:
        prefix = f"{name}.mark."
        if dotted.startswith(prefix):
            return dotted[len(prefix) :]
    for name in mark_names:
        prefix = f"{name}."
        if dotted.startswith(prefix):
            return dotted[len(prefix) :]
    return None


def _parametrized_values(
    node: ast.AST,
    aliases: tuple[set[str], set[str]] | None = None,
) -> set[str]:
    """Arguments supplied directly by parametrize rather than by fixtures."""

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set()
    direct: set[str] = set()
    aliases = aliases or ({"pytest"}, {"mark"})
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and _pytest_mark_kind(decorator, aliases) == "parametrize"
            and decorator.args
        ):
            continue
        names_node = decorator.args[0]
        if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
            names = {name.strip() for name in names_node.value.split(",") if name.strip()}
        elif isinstance(names_node, (ast.List, ast.Tuple)):
            names = {
                item.value
                for item in names_node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
        else:
            continue
        all_indirect = False
        indirect: set[str] = set()
        for keyword in decorator.keywords:
            if keyword.arg != "indirect":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                all_indirect = True
            elif isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                indirect = {
                    item.value
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
            else:
                # Dynamic indirectness cannot prove a fixture request.
                indirect = set()
        if all_indirect:
            continue
        direct.update(names - indirect)
    return direct


def _usefixtures_values(
    node: ast.AST,
    aliases: tuple[set[str], set[str]],
) -> set[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set()
    requested: set[str] = set()
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and _pytest_mark_kind(decorator, aliases) == "usefixtures"
        ):
            continue
        requested.update(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        )
    return requested


def _test_fixture_requests(data: bytes | None) -> set[str]:
    if not data:
        return set()
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return set()
    parsed = parse_python(data, collect_tests=True)
    if not parsed.parse_ok:
        return set()
    aliases = _pytest_mark_aliases(tree)
    functions: dict[str, tuple[ast.AST, tuple[ast.ClassDef, ...]]] = {}

    def index(
        node: ast.AST,
        prefix: str = "",
        classes: tuple[ast.ClassDef, ...] = (),
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[f"{prefix}{child.name}"] = (child, classes)
                index(child, f"{prefix}{child.name}.", classes)
            elif isinstance(child, ast.ClassDef):
                index(child, f"{prefix}{child.name}.", (*classes, child))

    index(tree)
    requested: set[str] = set()
    for unit in parsed.units:
        indexed = functions.get(unit.qualname.split("#", 1)[0])
        if indexed is not None:
            node, classes = indexed
            decorated = (*classes, node)
            direct = set().union(
                *(_parametrized_values(item, aliases) for item in decorated)
            )
            requested.update(set(unit.side.params) - direct)
            requested.update(
                set().union(*(_usefixtures_values(item, aliases) for item in decorated))
            )
    return requested


def _active_fixture_imports(
    test_path: str,
    test_data: bytes | None,
    conftest_sources: Mapping[str, bytes | None],
    *,
    fixture_binding_reader: Callable[[bytes | None], Mapping[str, _FixtureBinding]]
    | None = None,
    test_fixture_requests: Iterable[str] | None = None,
) -> set[str]:
    """Imports reached through requested/autouse fixtures visible to one test."""

    binding_reader = fixture_binding_reader or _fixture_bindings
    definitions: dict[str, _FixtureBinding] = {}
    autouse: set[str] = set()
    for path in sorted(conftest_sources, key=lambda item: (item.count("/"), item)):
        if not _scope_applies(path.rpartition("/")[0], test_path):
            continue
        bindings = binding_reader(conftest_sources[path])
        autouse.update(name for name, binding in bindings.items() if binding.autouse)
        definitions.update(bindings)
    # A test-module fixture is the closest definition and therefore overrides
    # a same-named fixture from any ancestor conftest.
    local = binding_reader(test_data)
    autouse.update(name for name, binding in local.items() if binding.autouse)
    definitions.update(local)

    requested = (
        _test_fixture_requests(test_data)
        if test_fixture_requests is None
        else set(test_fixture_requests)
    )
    pending = list(requested | autouse)
    active: set[str] = set()
    imports: set[str] = set()
    while pending:
        name = pending.pop()
        if name in active:
            continue
        active.add(name)
        binding = definitions.get(name)
        if binding is None:
            continue
        imports.update(binding.imports)
        pending.extend(binding.dependencies - active)
    return imports


def _active_test_imports(
    data: bytes | None,
    *,
    test_fixture_requests: Iterable[str] | None = None,
) -> set[str]:
    """Absolute imports executed by a collected test, fixture or called helper."""

    if not data:
        return set()
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return set()
    parsed = parse_python(data, collect_tests=True)
    if not parsed.parse_ok:
        return set()

    functions: dict[str, ast.AST] = {}

    def index(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[f"{prefix}{child.name}"] = child
                index(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                index(child, f"{prefix}{child.name}.")

    index(tree)
    top_level = {
        stmt.name: stmt
        for stmt in tree.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    active_scopes: list[ast.AST] = []
    for unit in parsed.units:
        qual = unit.qualname.split("#", 1)[0]
        node = functions.get(qual)
        if node is not None:
            active_scopes.append(node)
        for name in unit.side.invoked:
            # A parameter-local call is either a requested fixture (handled
            # below) or a direct parametrized value; it cannot resolve to a
            # same-named top-level helper/fixture by lexical name.
            if name in unit.side.params:
                continue
            helper = top_level.get(name)
            if helper is not None:
                active_scopes.append(helper)
    requested = (
        _test_fixture_requests(data)
        if test_fixture_requests is None
        else set(test_fixture_requests)
    )
    for name in requested | set(parsed.autouse_fixtures):
        fixture = top_level.get(name)
        if fixture is not None:
            active_scopes.append(fixture)

    # Module imports execute before collection, but an unused import is not
    # enough to call the imported module the assertion's subject.  Its local
    # binding must be consumed by one of the live scopes above.  Scope-local
    # imports apply the same rule within that scope.
    synthetic_module = ast.Module(body=list(tree.body), type_ignores=[])
    used_by_live_scope: set[str] = set()
    for scope in active_scopes:
        used_by_live_scope.update(_scope_global_loads(scope))

    active = _import_targets(synthetic_module, used_by_live_scope)
    for scope in active_scopes:
        active |= _import_targets(scope)
    return active


def _module_relpaths(module: str) -> tuple[str, str]:
    rel = module.replace(".", "/")
    return f"{rel}.py", f"{rel}/__init__.py"


def _provider_entries(module: str, paths: Iterable[str]) -> list[tuple[str, str]]:
    file_rel, package_rel = _module_relpaths(module)
    entries: list[tuple[str, str]] = []
    for path in sorted(set(paths)):
        for rel in (file_rel, package_rel):
            if path == rel:
                entries.append(("", path))
            elif path.endswith("/" + rel):
                entries.append((path[: -(len(rel) + 1)], path))
    return entries


def _plan_provider_entries(
    module: str, roots: Sequence[str], paths: Iterable[str]
) -> list[tuple[str, str]]:
    """Exact module providers rooted in one concrete search plan.

    ``_provider_entries`` intentionally discovers every suffix interpretation
    while building the repository index.  That broad inventory is not valid
    evidence that a same-path provider had an executable alternate: a path
    such as ``vendor/app/value.py`` is irrelevant unless ``vendor`` is an
    actual root in this plan.
    """

    allowed = set(_dedupe_roots(roots))
    return [
        (root, path)
        for root, path in _provider_entries(module, paths)
        if root in allowed
    ]


def _package_init_paths(module: str, paths: Iterable[str]) -> set[str]:
    parts = module.split(".")
    rels = [f"{'/'.join(parts[:i])}/__init__.py" for i in range(1, len(parts))]
    return {
        path
        for path in paths
        if any(path == rel or path.endswith("/" + rel) for rel in rels)
    }


def _provider_package_chain(module: str, root: str, paths: Iterable[str]) -> tuple[str, ...]:
    """Regular-package initializers executed before the selected leaf."""

    path_set = set(paths)
    parts = module.split(".")
    return tuple(
        init
        for i in range(1, len(parts))
        if (init := _join(root, f"{'/'.join(parts[:i])}/__init__.py")) in path_set
    )


def _join(root: str, rel: str) -> str:
    return f"{root.rstrip('/')}/{rel}" if root else rel


def _directory_exists(directory: str, paths: set[str]) -> bool:
    prefix = directory.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in paths)


def _extends_package_path(data: bytes | None) -> bool:
    if not data:
        return False
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return False
    bindings: dict[str, str] = {}

    def is_extend_call(node: ast.AST | None) -> bool:
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            return False
        name = _dotted(node.func)
        direct = bindings.get(name) == "extend_path"
        dotted = name.endswith(".extend_path") and bindings.get(
            name.rpartition(".")[0]
        ) == "pkgutil"
        if not direct and not dotted:
            return False
        return (
            isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__path__"
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "__name__"
        )

    def assigned_names(target: ast.AST | None) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return {
                name
                for element in target.elts
                for name in assigned_names(element)
            }
        if isinstance(target, ast.Starred):
            return assigned_names(target.value)
        return set()

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "pkgutil":
                    bindings[local] = "pkgutil"
                else:
                    bindings.pop(local, None)
            continue
        if isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if stmt.module == "pkgutil" and alias.name == "extend_path":
                    bindings[local] = "extend_path"
                else:
                    bindings.pop(local, None)
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(
                isinstance(target, ast.Name) and target.id == "__path__"
                for target in targets
            ) and is_extend_call(stmt.value):
                return True
            for target in targets:
                for name in assigned_names(target):
                    bindings.pop(name, None)
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.pop(stmt.name, None)
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                for name in assigned_names(target):
                    bindings.pop(name, None)
    return False


def _selected_provider(
    module: str,
    roots: Sequence[str],
    paths: Iterable[str],
    contents: Mapping[str, bytes | None] | None = None,
) -> tuple[str, str] | None:
    path_set = set(paths)
    ordered = list(_dedupe_roots(roots))
    # Walk package prefixes using Python's regular-vs-namespace rule.  A
    # regular package found later on sys.path beats namespace portions found
    # earlier; a pkgutil.extend_path package deliberately keeps those later
    # locations.  Looking only at the final path suffix gets this wrong and
    # reports shadows Python would never import.
    locations: list[tuple[str, str]] = [(root, root) for root in ordered]
    parts = module.split(".")
    for part in parts[:-1]:
        candidates: list[tuple[str, str, str]] = []
        for origin, directory in locations:
            child = _join(directory, part)
            init = f"{child}/__init__.py"
            if init in path_set:
                candidates.append((origin, child, init))
        if candidates:
            origin, child, init = candidates[0]
            next_locations = [(origin, child)]
            if _extends_package_path((contents or {}).get(init)):
                for other_origin, directory in locations:
                    other = _join(directory, part)
                    if other != child and _directory_exists(other, path_set):
                        next_locations.append((other_origin, other))
            locations = next_locations
        else:
            locations = [
                (origin, child)
                for origin, directory in locations
                if _directory_exists((child := _join(directory, part)), path_set)
            ]
        if not locations:
            return None

    leaf = parts[-1]
    for origin, directory in locations:
        file_path = _join(directory, f"{leaf}.py")
        package_path = _join(directory, f"{leaf}/__init__.py")
        if package_path in path_set:
            return origin, package_path
        if file_path in path_set:
            return origin, file_path
    return None


_MAX_SOURCE_KEY_PARSE_BYTES = 128_000


def _bytes_source_key(data: bytes) -> tuple[str, str]:
    """Bounded, fail-closed identity when AST equivalence is unavailable."""

    return "sha256", hashlib.sha256(data).hexdigest()


def _source_key(data: bytes | None) -> tuple[str, str] | None:
    if data is None:
        return None
    if len(data) > _MAX_SOURCE_KEY_PARSE_BYTES:
        return _bytes_source_key(data)
    try:
        tree = ast.parse(_decode(data))
        return "ast", ast.dump(tree, include_attributes=False)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        # Attacker-controlled Python can exhaust the recursive AST builder or
        # dumper well below the engine's one-megabyte source ceiling.  Raw
        # content identity is conservative (a change stays changed), bounded,
        # and never turns an unreadable provider into equivalence credit.
        return _bytes_source_key(data)


def _provider_execution_key(
    module: str,
    selected: tuple[str, str],
    paths: Iterable[str],
    contents: Mapping[str, bytes | None],
    *,
    source_keyer: Callable[[bytes | None], tuple[str, str] | None] | None = None,
) -> tuple[tuple[str, str], ...] | None:
    """AST keys for every executed package initializer and the leaf."""

    root, provider = selected
    executed = (*_provider_package_chain(module, root, paths), provider)
    keyer = source_keyer or _source_key
    keys = tuple(keyer(contents.get(path)) for path in executed)
    if any(key is None for key in keys):
        return None
    return tuple(key for key in keys if key is not None)


def _changed_provider(
    module: str,
    plan: SearchPlan,
    before_paths: Iterable[str],
    after_paths: Iterable[str],
    contents: Mapping[str, bytes | None],
    *,
    added_paths: set[str],
    removed_paths: set[str] | None = None,
    structural_paths: set[str] | None = None,
    semantic_paths: set[str] | None = None,
    before_contents: Mapping[str, bytes | None] | None = None,
    allow_equivalent: bool = False,
    provider_keyer: Callable[
        [str, tuple[str, str], Iterable[str], Mapping[str, bytes | None]],
        tuple[tuple[str, str], ...] | None,
    ]
    | None = None,
) -> tuple[str, str] | None:
    """The one family predicate: did the imported module change provider?"""

    base_contents = contents if before_contents is None else before_contents
    before = _selected_provider(module, plan.before_roots, before_paths, base_contents)
    after = _selected_provider(module, plan.after_roots, after_paths, contents)
    if before is None or after is None:
        return None
    keyer = provider_keyer or _provider_execution_key
    before_key = keyer(module, before, before_paths, base_contents)
    after_key = keyer(module, after, after_paths, contents)
    if before_key is None or after_key is None:
        return None
    if before[1] == after[1]:
        # Two-commit plant: the already-winning provider was executable-
        # equivalent to an alternate provider at base, then changed in this
        # diff.  An ordinary edit to an intentionally divergent duplicate is
        # not this family and remains an honest negative.
        semantic = semantic_paths or set()
        executed = {
            *_provider_package_chain(module, before[0], before_paths),
            *_provider_package_chain(module, after[0], after_paths),
            before[1],
        }
        if not (executed & semantic) or before_key == after_key:
            return None
        alternate_after_keys = [
            keyer(module, (root, path), after_paths, contents)
            for root, path in _plan_provider_entries(
                module, plan.before_roots, before_paths
            )
            if path != before[1]
            and path in set(after_paths)
            and keyer(
                module, (root, path), before_paths, base_contents
            )
            == before_key
        ]
        if any(key is not None and key != after_key for key in alternate_after_keys):
            return before[1], after[1]
        if allow_equivalent and any(key == after_key for key in alternate_after_keys):
            return before[1], after[1]
        return None
    package_shape_changed = bool(
        _package_init_paths(module, added_paths | (structural_paths or set()))
    )
    if (
        after[1] not in added_paths
        and before[1] not in (removed_paths or set())
        and not package_shape_changed
        and plan.before_roots == plan.after_roots
    ):
        return None
    if before_key == after_key and not allow_equivalent:
        return None
    return before[1], after[1]


def _path_to_modules(path: str) -> set[str]:
    """All exact dotted-module interpretations under an ancestor search root."""

    if not path.endswith(".py"):
        return set()
    rel = path[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    parts = [part for part in rel.split("/") if part]
    out: set[str] = set()
    for i in range(len(parts)):
        tail = parts[i:]
        if all(part.isidentifier() for part in tail):
            out.add(".".join(tail))
    return out


def _module_from_root(path: str, root: str) -> str | None:
    prefix = root.rstrip("/") + "/" if root else ""
    if not path.startswith(prefix) or not path.endswith(".py"):
        return None
    rel = path[len(prefix) : -3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    parts = [part for part in rel.split("/") if part]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _side_paths(after_paths: set[str], changes: Sequence[FileChange]) -> tuple[set[str], set[str]]:
    before = set(after_paths)
    after = set(after_paths)
    for change in changes:
        path = change.path.replace("\\", "/")
        old = (change.old_path or "").replace("\\", "/")
        if change.status == "added":
            before.discard(path)
            after.add(path)
        elif change.status == "deleted":
            before.add(path)
            after.discard(path)
        elif old and old != path:
            before.add(old)
            before.discard(path)
            after.discard(old)
            after.add(path)
    return before, after


def _side_source(
    path: str,
    side: str,
    changes: Mapping[str, FileChange],
    snapshot: Mapping[str, bytes | None],
) -> bytes | None:
    change = changes.get(path)
    if change is not None:
        return change.before if side == "before" else change.after
    return snapshot.get(path)


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


def _scope_applies(scope_dir: str, test_path: str) -> bool:
    if not scope_dir:
        return True
    return test_path == scope_dir or test_path.startswith(scope_dir.rstrip("/") + "/")


def _invocation_applies(invocation: _RunnerInvocation, test_path: str) -> bool:
    if invocation.scope is not None:
        return test_path in invocation.scope
    if not invocation.targets:
        return True
    for target in invocation.targets:
        if target.endswith(".py"):
            if test_path == target:
                return True
        elif _scope_applies(target, test_path):
            return True
    return False


_SHELL_GLOB_MAGIC = frozenset("*?[")


def _shell_glob_match(pattern: str, path: str) -> bool:
    """Match a literal, single-level POSIX shell pathname expansion.

    ``**`` depends on shell options and is therefore not claimed.  Ordinary
    ``*``, ``?`` and bracket expressions are provable from the repository
    inventory; unlike ``fnmatch`` over a whole string, they never cross ``/``.
    """

    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(pattern_parts) != len(path_parts) or "**" in pattern_parts:
        return False
    return all(
        not (part.startswith(".") and not glob.startswith("."))
        and fnmatchcase(part, glob)
        for glob, part in zip(pattern_parts, path_parts)
    )


def _expand_invocation_targets(
    invocation: _RunnerInvocation, test_paths: Sequence[str]
) -> _RunnerInvocation | None:
    """Resolve targets and their exact test scope against one side's inventory."""

    candidates = set(test_paths)
    for path in test_paths:
        directory = path.rpartition("/")[0]
        while directory:
            candidates.add(directory)
            directory = directory.rpartition("/")[0]
    expanded: list[str] = []
    for target in invocation.targets:
        if not any(char in target for char in _SHELL_GLOB_MAGIC):
            expanded.append(target)
            continue
        matches = sorted(
            path for path in candidates if _shell_glob_match(target, path)
        )
        if not matches:
            # Shell behaviour for an unmatched pattern is environment-specific
            # (literal, nullglob, or hard failure), so it cannot safely widen
            # the invocation to every test.
            return None
        expanded.extend(matches)
    normalised_targets = _dedupe_roots(expanded)
    if not invocation.targets:
        scope = tuple(sorted(test_paths))
    else:
        selected: set[str] = set()
        for target in normalised_targets:
            if target in test_paths:
                selected.add(target)
            else:
                selected.update(
                    path
                    for path in test_paths
                    if _scope_applies(target, path)
                )
        scope = tuple(sorted(selected))
    return replace(
        invocation,
        targets=normalised_targets,
        scope=scope,
        raw_targets=(
            invocation.targets
            if invocation.raw_targets is None
            else invocation.raw_targets
        ),
    )


def _invocation_scope_score(
    before: _RunnerInvocation, after: _RunnerInvocation
) -> int:
    """How strongly two commands identify the same pytest oracle scope."""

    if (
        before.raw_targets is not None
        and before.raw_targets == after.raw_targets
        and before.cwd == after.cwd
    ):
        return 5
    if before.scope is not None and after.scope is not None:
        if not before.scope or before.scope != after.scope:
            return 0
        return 4 if before.cwd == after.cwd else 3
    before_targets = frozenset(before.targets)
    after_targets = frozenset(after.targets)
    return 4 if before_targets == after_targets else 0


def _align_runner_invocations(
    before: Sequence[_RunnerInvocation], after: Sequence[_RunnerInvocation]
) -> tuple[tuple[_RunnerInvocation, _RunnerInvocation], ...]:
    """Align commands by oracle scope and retain every head invocation.

    Exact unchanged commands are paired first so reordering is inert.  A
    duplicate head command may reuse the matching base command: otherwise an
    appended stand-in invocation would disappear.  A genuinely new scope gets
    a conservative repository-environment baseline with the same targets.
    Removed head commands cannot affect the runtime oracle and are omitted.
    """

    unused = set(range(len(before)))
    pairs: list[tuple[_RunnerInvocation, _RunnerInvocation]] = []
    for after_index, current in enumerate(after):
        ranked: list[tuple[int, int, int, int, int]] = []
        for before_index, candidate in enumerate(before):
            score = _invocation_scope_score(candidate, current)
            if not score:
                continue
            identical = int(candidate == current)
            available = int(before_index in unused)
            distance = -abs(before_index - after_index)
            ranked.append((identical, score, available, distance, before_index))
        if ranked:
            before_index = max(ranked)[-1]
            unused.discard(before_index)
            baseline = before[before_index]
        else:
            baseline = replace(
                current,
                roots=(),
                mode=None,
                config_path=None,
            )
        pairs.append((baseline, current))
    return tuple(pairs)


def _runner_control(path: str, change: FileChange, config: Config) -> bool:
    """Only actual runner/CI files can make an environment assignment live."""

    before, after = _runner_invocation_sides(path, change, config)
    return before != after


def _runner_invocation_sides(
    path: str, change: FileChange, config: Config
) -> tuple[tuple[_RunnerInvocation, ...], tuple[_RunnerInvocation, ...]]:
    old_path = (change.old_path or path).replace("\\", "/")
    return (
        _runner_invocations_live(old_path, change.before, config),
        _runner_invocations_live(path, change.after, config),
    )


def _runner_search_sides(
    path: str, change: FileChange, config: Config
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Live runner roots on each side, including a rename across roles."""

    before_invocations, after_invocations = _runner_invocation_sides(path, change, config)
    before = before_invocations[-1].roots if before_invocations else ()
    after = after_invocations[-1].roots if after_invocations else ()
    return before, after


def _runner_invocations_live(
    path: str, data: bytes | None, config: Config
) -> tuple[_RunnerInvocation, ...]:
    live = config.role_of(path) == "ci" or _is_runner_script(path, data, data)
    return _runner_invocations(path, data) if live else ()


def _runner_roots(path: str, data: bytes | None, config: Config) -> tuple[str, ...]:
    invocations = _runner_invocations_live(path, data, config)
    return invocations[-1].roots if invocations else ()


def _could_be_extensionless_runner(path: str) -> bool:
    """Could this inventory path need a shebang read to identify a runner?"""

    base = path.rsplit("/", 1)[-1]
    return bool(base) and "." not in base


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
    before_path = (change.old_path or path).replace("\\", "/")
    before_named = before_path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
    after_named = path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
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
    old_path = (change.old_path or path).replace("\\", "/")
    if (
        path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
        or old_path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
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


class _ShadowAnalysisCache:
    """Revision-local memoisation keyed by immutable source content.

    A detector call describes exactly one before/head pair.  Keeping this
    cache local to that call avoids stale path-only answers across commits,
    while sharing unchanged bytes between sides and between tests that use
    the same conftest or provider chain.
    """

    def __init__(self) -> None:
        self._source_keys: dict[bytes | None, tuple[str, str] | None] = {}
        self._fixture_bindings: dict[
            bytes | None, Mapping[str, _FixtureBinding]
        ] = {}
        self._fixture_requests: dict[bytes | None, frozenset[str]] = {}
        self._test_imports: dict[bytes | None, frozenset[str]] = {}
        self._fixture_imports: dict[
            tuple[
                str,
                bytes | None,
                tuple[tuple[str, bytes | None], ...],
            ],
            frozenset[str],
        ] = {}
        self._provider_keys: dict[
            tuple[
                str,
                tuple[str, str],
                frozenset[str],
                tuple[tuple[str, bytes | None], ...],
            ],
            tuple[tuple[str, str], ...] | None,
        ] = {}

    def source_key(self, data: bytes | None) -> tuple[str, str] | None:
        if data not in self._source_keys:
            self._source_keys[data] = _source_key(data)
        return self._source_keys[data]

    def fixture_bindings(
        self, data: bytes | None
    ) -> Mapping[str, _FixtureBinding]:
        if data not in self._fixture_bindings:
            self._fixture_bindings[data] = MappingProxyType(
                _fixture_bindings(data)
            )
        return self._fixture_bindings[data]

    def fixture_requests(self, data: bytes | None) -> frozenset[str]:
        if data not in self._fixture_requests:
            self._fixture_requests[data] = frozenset(_test_fixture_requests(data))
        return self._fixture_requests[data]

    def active_test_imports(self, data: bytes | None) -> frozenset[str]:
        if data not in self._test_imports:
            self._test_imports[data] = frozenset(
                _active_test_imports(
                    data,
                    test_fixture_requests=self.fixture_requests(data),
                )
            )
        return self._test_imports[data]

    def active_fixture_imports(
        self,
        test_path: str,
        test_data: bytes | None,
        conftest_sources: Mapping[str, bytes | None],
    ) -> frozenset[str]:
        conftest_key = tuple(sorted(conftest_sources.items()))
        key = (test_path, test_data, conftest_key)
        if key not in self._fixture_imports:
            self._fixture_imports[key] = frozenset(
                _active_fixture_imports(
                    test_path,
                    test_data,
                    conftest_sources,
                    fixture_binding_reader=self.fixture_bindings,
                    test_fixture_requests=self.fixture_requests(test_data),
                )
            )
        return self._fixture_imports[key]

    def provider_execution_key(
        self,
        module: str,
        selected: tuple[str, str],
        paths: Iterable[str],
        contents: Mapping[str, bytes | None],
    ) -> tuple[tuple[str, str], ...] | None:
        path_set = frozenset(paths)
        root, provider = selected
        executed = (*_provider_package_chain(module, root, path_set), provider)
        content_key = tuple((path, contents.get(path)) for path in executed)
        key = (module, selected, path_set, content_key)
        if key not in self._provider_keys:
            self._provider_keys[key] = _provider_execution_key(
                module,
                selected,
                path_set,
                contents,
                source_keyer=self.source_key,
            )
        return self._provider_keys[key]


_HEAD_SEARCH_NEEDLE_BATCH = 128


def _normalized_head_search_path(path: object) -> str | None:
    """A safely normalized repository-relative path, or no attestation."""

    if not isinstance(path, str):
        return None
    normalized = path.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or (
            len(normalized) >= 2
            and normalized[0].isalpha()
            and normalized[1] == ":"
        )
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        return None
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return normalized


def _complete_head_search(
    head_searcher: Callable[[list[str]], Sequence[str] | HeadSearchResult] | None,
    modules: Iterable[str],
) -> set[str] | None:
    """Return authoritative matches, or ``None`` for the fail-closed path."""

    if head_searcher is None:
        return None
    roots = sorted({module.split(".", 1)[0] for module in modules})
    matches: set[str] = set()
    for start in range(0, len(roots), _HEAD_SEARCH_NEEDLE_BATCH):
        needles = roots[start : start + _HEAD_SEARCH_NEEDLE_BATCH]
        try:
            result = head_searcher(needles)
            if (
                not isinstance(result, HeadSearchResult)
                or result.complete is not True
            ):
                return None
            normalized = {
                _normalized_head_search_path(path)
                for path in result
            }
            if None in normalized:
                return None
            matches.update(path for path in normalized if path is not None)
        except Exception:
            # Search is only a narrowing optimisation.  An incomplete result,
            # callback error, or malformed path must retain the complete tree
            # walk below rather than becoming proof that no oracle imports it.
            return None
    return matches


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


def find_runtime_subject_shadows(
    changes: Sequence[FileChange],
    config: Config,
    third_party_roots: Iterable[str] = (),
    *,
    head_path_lister: Callable[[], Sequence[str]] | None = None,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None = None,
    head_searcher: Callable[
        [list[str]], Sequence[str] | HeadSearchResult
    ]
    | None = None,
    include_equivalent: bool = False,
) -> list[SubjectShadow]:
    """Return provider changes for existing first-party test imports."""

    analysis = _ShadowAnalysisCache()
    third_party = set(third_party_roots)
    normally_relevant = _relevant(changes, config)
    # A same-path provider mutation matters only when repository inventory is
    # available to prove an existing competing provider and live test import.
    # Direct engine users (including the frozen perf gate) provide neither;
    # let an ordinary modified production file stay on the established lazy
    # path without parsing attacker-controlled bytes a second time.
    can_inventory_staged = head_searcher is not None or (
        head_path_lister is not None and head_batch_reader is not None
    )
    if not normally_relevant and not can_inventory_staged:
        return []
    # First use paths alone to prove that an alternate provider is even
    # possible.  AST-equivalence is substantially more expensive and is only
    # needed for modified files that survive that collision index.
    provisional_staged_paths = {
        change.path.replace("\\", "/")
        for change in changes
        if change.path.replace("\\", "/").endswith(".py")
        and change.before is not None
        and change.after is not None
    }
    # Proving an already-winning two-commit plant requires repository
    # inventory.  The production git frontend supplies a batched searcher;
    # without it, keep ordinary Python edits on the established lazy path
    # rather than turning every source change into a whole-tree scan.
    provisional_staged_paths = (
        provisional_staged_paths if can_inventory_staged else set()
    )
    if not normally_relevant and not provisional_staged_paths:
        return []
    change_by_path = {c.path.replace("\\", "/"): c for c in changes}
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
    changed_config_paths = {
        path
        for path in changed_control_paths
        if path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
        or (change_by_path[path].old_path or path)
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        in _PYTEST_CONFIGS
    }
    search_order_changed = bool(changed_control_paths)
    inventory = [
        path.replace("\\", "/")
        for path in (head_path_lister() if head_path_lister is not None else [])
    ]
    listed = [
        path
        for path in inventory
        if path.endswith(".py")
        or path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
        or config.role_of(path) == "ci"
        or _runner_shape(path, None, None)
        or _could_be_extensionless_runner(path)
    ]
    after_paths = set(listed)
    after_paths.update(path for path, c in change_by_path.items() if c.after is not None)
    after_paths.difference_update(path for path, c in change_by_path.items() if c.after is None)
    before_paths, after_paths = _side_paths(after_paths, changes)
    added_paths = after_paths - before_paths
    removed_paths = before_paths - after_paths

    config_paths = sorted(
        p for p in before_paths | after_paths if p.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
    )
    conftest_paths = sorted(
        p for p in before_paths | after_paths if _is_conftest_path(p)
    )
    changed_runner_paths = sorted(
        path
        for path, change in change_by_path.items()
        if path.rsplit("/", 1)[-1] not in _PYTEST_CONFIGS
        and (change.old_path or path).replace("\\", "/").rsplit("/", 1)[-1]
        not in _PYTEST_CONFIGS
        and not _is_conftest_path(path)
        and not _is_conftest_path((change.old_path or path).replace("\\", "/"))
        and any(_runner_invocation_sides(path, change, config))
    )
    runner_snapshot_paths = sorted(
        path
        for path in before_paths | after_paths
        if path.rsplit("/", 1)[-1] not in _PYTEST_CONFIGS
        and not _is_conftest_path(path)
        and (
            config.role_of(path) == "ci"
            or _runner_shape(path, None, None)
            or _could_be_extensionless_runner(path)
        )
    )

    # Candidate modules come from a new/semantically changed provider or from
    # paths under roots a changed control explicitly reorders. This is the
    # cheap stage before any repository source is read.
    modules: set[str] = set()
    for path in sorted(added_paths | removed_paths | provisional_staged_paths):
        modules |= _path_to_modules(path)
    if changed_config_paths:
        # Adding/deleting a higher-precedence but otherwise empty config can
        # mask an unchanged lower-precedence config. Its roots are not present
        # in the changed file, so inventory every exact module interpretation;
        # active imports and provider resolution still make the decision.
        for path in sorted(after_paths | before_paths):
            modules.update(_path_to_modules(path))
    added_packages = {
        package
        for path in added_paths
        if _is_package_init(path)
        for package in _path_to_modules(path)
    }
    package_shape_paths: set[str] = set()
    for path, change in change_by_path.items():
        if not _package_shape_change(path, change):
            continue
        old_path = (change.old_path or path).replace("\\", "/")
        if _is_package_init(old_path):
            package_shape_paths.add(old_path)
        if _is_package_init(path):
            package_shape_paths.add(path)
    semantic_packages = {
        package
        for path in provisional_staged_paths
        if _is_package_init(path)
        for package in _path_to_modules(path)
    }
    shape_packages = added_packages | semantic_packages | {
        package
        for path in package_shape_paths
        for package in _path_to_modules(path)
    }
    if shape_packages:
        for path in sorted(after_paths | before_paths):
            for module in _path_to_modules(path):
                parts = module.split(".")
                if any(
                    ".".join(parts[:i]) in shape_packages
                    for i in range(1, len(parts))
                ):
                    modules.add(module)
    # The repository root is always a real process search location. Pairing it
    # with the roots named by the changed control catches a newly prepended
    # shadow without inventing arbitrary source roots from filename suffixes.
    changed_roots: set[str] = {""} if search_order_changed else set()
    import_mode_changed = False
    for path, change in sorted(change_by_path.items()):
        old_path = (change.old_path or path).replace("\\", "/")
        old_config = old_path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
        new_config = path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
        if old_config or new_config:
            before_search = (
                _config_search(old_path, change.before) if old_config else ((), "prepend")
            )
            after_search = (
                _config_search(path, change.after) if new_config else ((), "prepend")
            )
            changed_roots.update(before_search[0])
            changed_roots.update(after_search[0])
            import_mode_changed |= before_search[1] != after_search[1]
            continue
        old_conftest = _is_conftest_path(old_path)
        new_conftest = _is_conftest_path(path)
        if old_conftest or new_conftest:
            if old_conftest:
                changed_roots.update(_sys_path_roots(old_path, change.before))
            if new_conftest:
                changed_roots.update(_sys_path_roots(path, change.after))
            continue
        if path in changed_runner_paths and _runner_control(path, change, config):
            before_invocations, after_invocations = _runner_invocation_sides(
                path, change, config
            )
            for invocation in (*before_invocations, *after_invocations):
                changed_roots.update(invocation.roots)
            import_mode_changed |= tuple(item.mode for item in before_invocations) != tuple(
                item.mode for item in after_invocations
            )
    if import_mode_changed or package_shape_paths:
        for path in sorted(before_paths | after_paths):
            if config.role_of(path) == "test" and collectable(path):
                changed_roots.add(_pytest_import_root(path, before_paths))
                changed_roots.add(_pytest_import_root(path, after_paths))
    by_module: dict[str, set[str]] = {}
    for root in sorted(changed_roots):
        for path in sorted(after_paths | before_paths):
            module = _module_from_root(path, root)
            if module is not None:
                by_module.setdefault(module, set()).add(path)
    modules.update(module for module, providers in by_module.items() if len(providers) > 1)
    modules = {m for m in modules if m and m.split(".", 1)[0] not in third_party}
    indexed_modules = set(modules)
    for module in modules:
        parts = module.split(".")
        indexed_modules.update(".".join(parts[:i]) for i in range(1, len(parts)))
    provider_index: dict[str, set[str]] = {}
    for path in sorted(before_paths | after_paths):
        for module in _path_to_modules(path) & indexed_modules:
            provider_index.setdefault(module, set()).add(path)
    # A changed provider necessarily has two different leaf locations across
    # the two sides. Discard ordinary new modules before reading any source.
    modules = {
        module
        for module in modules
        if len(provider_index.get(module, ())) > 1
    }
    if not modules:
        return []

    indexed_survivors = set(modules)
    for module in modules:
        parts = module.split(".")
        indexed_survivors.update(
            ".".join(parts[:index]) for index in range(1, len(parts))
        )
    semantic_provider_paths = {
        path
        for path in provisional_staged_paths
        if (
            _path_to_modules(path) & indexed_survivors
            and analysis.source_key(change_by_path[path].before)
            != analysis.source_key(change_by_path[path].after)
        )
    }
    staged_candidate_paths = semantic_provider_paths
    if not normally_relevant and not staged_candidate_paths:
        return []

    # Search only after the tree proves that a competing provider exists.
    # Production frontends return an explicitly complete result; a legacy
    # sequence, exception, or incomplete result leaves ``presearched`` as
    # None and therefore retains the complete test inventory below.
    presearched = _complete_head_search(head_searcher, modules)
    if presearched is not None and not presearched:
        return []

    eligible_tests = {
        path
        for path in after_paths
        if config.role_of(path) == "test" and collectable(path)
    }
    if presearched is None:
        # An untrusted/capped result can narrow nothing. This path is
        # intentionally expensive and complete rather than silently weak.
        test_paths = sorted(eligible_tests)
    else:
        matched_conftests = {
            path
            for path in presearched
            if path in after_paths and _is_conftest_path(path)
        }
        # A subject import may live only in an ancestor conftest fixture. A
        # complete grep shortlist therefore closes each matching conftest over
        # its pytest scope instead of retaining direct test hits alone.
        test_paths = sorted(
            (eligible_tests & presearched)
            | {
                test_path
                for test_path in eligible_tests
                if any(
                    _scope_applies(conftest.rpartition("/")[0], test_path)
                    for conftest in matched_conftests
                )
            }
        )
    if not test_paths:
        return []
    conftest_paths = [
        path
        for path in conftest_paths
        if any(_scope_applies(path.rpartition("/")[0], test_path) for test_path in test_paths)
    ]

    # Phase one reads only controls and candidate tests. Their active imports
    # narrow an arbitrarily large package down before provider sources are
    # requested, so repository size cannot disable the detector via a cap.
    initial_reads = sorted(
        {
            *test_paths,
            *conftest_paths,
            *runner_snapshot_paths,
            *config_paths,
        }
        - set(side_change_by_path)
    )
    snapshot: dict[str, bytes | None] = {}
    if initial_reads and head_batch_reader is not None:
        read = head_batch_reader(initial_reads)
        missing = [path for path in initial_reads if read.get(path) is None]
        if missing:
            raise RuntimeError(
                "runtime-shadow snapshot read failed: " + ", ".join(missing[:3])
            )
        snapshot.update(read)
    for path, change in change_by_path.items():
        if change.after is not None:
            snapshot[path] = change.after

    before_conftests = {
        path: _side_source(path, "before", side_change_by_path, snapshot)
        for path in conftest_paths
        if path in before_paths
    }
    after_conftests = {
        path: _side_source(path, "after", side_change_by_path, snapshot)
        for path in conftest_paths
        if path in after_paths
    }
    imported_by_test: dict[str, set[str]] = {}
    active_modules: set[str] = set()
    for test_path in test_paths:
        after_source = _side_source(test_path, "after", change_by_path, snapshot)
        before_source = _side_source(test_path, "before", side_change_by_path, snapshot)
        imported = (
            (
                analysis.active_test_imports(before_source)
                | analysis.active_fixture_imports(
                    test_path, before_source, before_conftests
                )
            )
            & (
                analysis.active_test_imports(after_source)
                | analysis.active_fixture_imports(
                    test_path, after_source, after_conftests
                )
            )
            & modules
        )
        if imported:
            imported_by_test[test_path] = imported
            active_modules.update(imported)
    if not active_modules:
        return []
    modules = active_modules

    module_paths: dict[str, tuple[set[str], set[str]]] = {}
    provider_paths: set[str] = set()
    for module in modules:
        relevant = set(provider_index.get(module, ()))
        parts = module.split(".")
        for i in range(1, len(parts)):
            relevant.update(
                path
                for path in provider_index.get(".".join(parts[:i]), ())
                if path.endswith("/__init__.py")
            )
        provider_paths.update(relevant)
        module_paths[module] = (relevant & before_paths, relevant & after_paths)
    provider_reads = sorted(provider_paths - set(side_change_by_path) - set(snapshot))
    if provider_reads and head_batch_reader is not None:
        read = head_batch_reader(provider_reads)
        missing = [path for path in provider_reads if read.get(path) is None]
        if missing:
            raise RuntimeError(
                "runtime-shadow provider read failed: " + ", ".join(missing[:3])
            )
        snapshot.update(read)

    conftest_controls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for path in conftest_paths:
        before_sys = (
            _sys_path_roots(
                path, _side_source(path, "before", side_change_by_path, snapshot)
            )
            if path in before_paths
            else ()
        )
        after_sys = (
            _sys_path_roots(
                path, _side_source(path, "after", side_change_by_path, snapshot)
            )
            if path in after_paths
            else ()
        )
        if before_sys or after_sys:
            conftest_controls.append((path, before_sys, after_sys))
    runner_controls: list[tuple[str, _RunnerInvocation, _RunnerInvocation]] = []
    before_test_inventory = tuple(
        sorted(
            path
            for path in before_paths
            if config.role_of(path) == "test" and collectable(path)
        )
    )
    after_test_inventory = tuple(
        sorted(
            path
            for path in after_paths
            if config.role_of(path) == "test" and collectable(path)
        )
    )
    for path in changed_runner_paths:
        change = change_by_path[path]
        before_invocations, after_invocations = _runner_invocation_sides(
            path, change, config
        )
        before_invocations = tuple(
            expanded
            for invocation in before_invocations
            if (
                expanded := _expand_invocation_targets(
                    invocation, before_test_inventory
                )
            )
            is not None
        )
        after_invocations = tuple(
            expanded
            for invocation in after_invocations
            if (
                expanded := _expand_invocation_targets(
                    invocation, after_test_inventory
                )
            )
            is not None
        )
        runner_controls.extend(
            (path, before, after)
            for before, after in _align_runner_invocations(
                before_invocations, after_invocations
            )
        )
    for path in runner_snapshot_paths:
        if path in side_change_by_path:
            continue
        data = snapshot.get(path)
        for invocation in _runner_invocations_live(path, data, config):
            expanded = _expand_invocation_targets(
                invocation, after_test_inventory
            )
            if expanded is not None:
                runner_controls.append((path, expanded, expanded))

    contents = {path: snapshot.get(path) for path in provider_paths}
    before_contents = {
        path: (
            side_change_by_path[path].before
            if path in side_change_by_path and side_change_by_path[path].before is not None
            else snapshot.get(path)
        )
        for path in provider_paths
    }
    hits: list[SubjectShadow] = []
    seen: dict[tuple[str, str], int] = {}
    for test_path, imported in imported_by_test.items():
        before_sys: tuple[str, ...] = ()
        after_sys: tuple[str, ...] = ()
        sys_trigger: str | None = None
        # Parent conftests execute before nested conftests. Each prepend made
        # by the later file therefore sits ahead of the earlier one's roots.
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

        def config_side(
            side: str,
            paths: set[str],
            invocation: _RunnerInvocation | None,
        ) -> tuple[str | None, tuple[str, ...], str]:
            config_contents = {
                path: _side_source(path, side, side_change_by_path, snapshot)
                for path in paths
                if path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
            }
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
                (
                    _side_source(cfg, side, side_change_by_path, snapshot)
                    if cfg
                    else None
                ),
            )
            mode = (
                invocation.mode
                if invocation is not None and invocation.mode is not None
                else configured_mode
            )
            return cfg, roots, mode

        def selected_controls(before_cfg: str | None, after_cfg: str | None) -> set[str]:
            return {
                path
                for path, change in change_by_path.items()
                if (
                    path.rsplit("/", 1)[-1] in _PYTEST_CONFIGS
                    or (change.old_path or path)
                    .replace("\\", "/")
                    .rsplit("/", 1)[-1]
                    in _PYTEST_CONFIGS
                )
                and _config_change(path, change)
                and (
                    path == after_cfg
                    or (change.old_path or path).replace("\\", "/") == before_cfg
                )
            }

        plans: list[SearchPlan] = []
        if runner_controls:
            for runner_path, before_invocation, after_invocation in runner_controls:
                # The same existing oracle must be exercised on both sides.
                if not (
                    _invocation_applies(before_invocation, test_path)
                    and _invocation_applies(after_invocation, test_path)
                ):
                    continue
                before_cfg, before_cfg_roots, before_mode = config_side(
                    "before", before_paths, before_invocation
                )
                after_cfg, after_cfg_roots, after_mode = config_side(
                    "after", after_paths, after_invocation
                )
                controls = selected_controls(before_cfg, after_cfg)
                trigger = sys_trigger or next(
                    iter(sorted(controls)), runner_path
                )
                # Configured pythonpath is inserted after process startup and
                # precedes PYTHONPATH; conftest mutations execute later still.
                plans.append(
                    SearchPlan(
                        trigger,
                        _dedupe_roots(
                            [*before_sys, *before_cfg_roots, *before_invocation.roots]
                        ),
                        _dedupe_roots(
                            [*after_sys, *after_cfg_roots, *after_invocation.roots]
                        ),
                        before_mode,
                        after_mode,
                        control_paths=tuple(sorted(controls)),
                    )
                )
        else:
            # With no concrete runner, model one implicit invocation over the
            # complete discovered test set.  The authoritative grep shortlist
            # controls parsing cost only; it must not change pytest's config
            # discovery root by pretending unrelated collected tests vanished.
            implicit = _RunnerInvocation((), tuple(sorted(eligible_tests)))
            before_cfg, before_cfg_roots, before_mode = config_side(
                "before", before_paths, implicit
            )
            after_cfg, after_cfg_roots, after_mode = config_side(
                "after", after_paths, implicit
            )
            controls = selected_controls(before_cfg, after_cfg)
            plans.append(
                SearchPlan(
                    sys_trigger
                    or next(iter(sorted(controls)), "pytest import path"),
                    _dedupe_roots([*before_sys, *before_cfg_roots]),
                    _dedupe_roots([*after_sys, *after_cfg_roots]),
                    before_mode,
                    after_mode,
                    control_paths=tuple(sorted(controls)),
                )
            )
        unique_plans: dict[
            tuple[tuple[str, ...], tuple[str, ...], str, str], SearchPlan
        ] = {}
        for plan in plans:
            key = (plan.before_roots, plan.after_roots, plan.before_mode, plan.after_mode)
            if key in unique_plans:
                existing = unique_plans[key]
                unique_plans[key] = replace(
                    existing,
                    control_paths=tuple(
                        sorted({*existing.control_paths, *plan.control_paths})
                    ),
                )
            else:
                unique_plans[key] = plan
        for plan in unique_plans.values():
            for module in sorted(imported, key=lambda m: (-m.count("."), m)):
                scoped = SearchPlan(
                    plan.trigger,
                    _plan_roots(plan, test_path, before_paths, "before"),
                    _plan_roots(plan, test_path, after_paths, "after"),
                    plan.before_mode,
                    plan.after_mode,
                    plan.scope_dir,
                    plan.control_paths,
                )
                changed = _changed_provider(
                    module,
                    scoped,
                    module_paths[module][0],
                    module_paths[module][1],
                    contents,
                    added_paths=added_paths,
                    removed_paths=removed_paths,
                    structural_paths=package_shape_paths,
                    before_contents=before_contents,
                    semantic_paths=staged_candidate_paths,
                    allow_equivalent=include_equivalent,
                    provider_keyer=analysis.provider_execution_key,
                )
                if changed is None:
                    continue
                before_provider, after_provider = changed
                # The old provider is the evidence that this is first-party
                # code under test, rather than a test choosing between two
                # fixtures or two vendored third-party copies.
                before_selected = _selected_provider(
                    module, scoped.before_roots, module_paths[module][0], before_contents
                )
                after_selected = _selected_provider(
                    module, scoped.after_roots, module_paths[module][1], contents
                )
                if before_selected is None or after_selected is None:
                    continue
                before_key = analysis.provider_execution_key(
                    module, before_selected, module_paths[module][0], before_contents
                )
                after_key = analysis.provider_execution_key(
                    module, after_selected, module_paths[module][1], contents
                )
                if before_key is None or after_key is None:
                    continue
                if before_provider == after_provider:
                    # The selected path was already first in search order. It
                    # belongs to this family only when a first-party alternate
                    # had the same execution key immediately before this edit.
                    canonical_after_keys = [
                        analysis.provider_execution_key(
                            module,
                            (root, path),
                            module_paths[module][1],
                            contents,
                        )
                        for root, path in _plan_provider_entries(
                            module,
                            scoped.before_roots,
                            module_paths[module][0],
                        )
                        if path != before_provider
                        and path in module_paths[module][1]
                        and config.role_of(path) == "prod"
                        and analysis.provider_execution_key(
                            module,
                            (root, path),
                            module_paths[module][0],
                            before_contents,
                        )
                        == before_key
                    ]
                    if not canonical_after_keys:
                        continue
                    reportable = any(
                        key is not None and key != after_key
                        for key in canonical_after_keys
                    )
                else:
                    if config.role_of(before_provider) != "prod":
                        continue
                    # An executable-equivalent location/search-order switch is
                    # retained only for evidence exclusion, not reported.
                    reportable = before_key != after_key
                after_root = after_selected[0]
                package_chain = _provider_package_chain(module, after_root, after_paths)
                shape_trigger = next(
                    (path for path in package_chain if path in package_shape_paths),
                    None,
                )
                if shape_trigger is None:
                    shape_trigger = next(
                        iter(sorted(_package_init_paths(module, package_shape_paths))),
                        None,
                    )
                provider_departed = before_provider in removed_paths
                effective_trigger = (
                    before_provider
                    if provider_departed
                    else after_provider
                    if before_provider == after_provider
                    else shape_trigger or plan.trigger
                )
                finding_path = (
                    before_provider
                    if provider_departed
                    else after_provider
                    if after_provider in added_paths or before_provider == after_provider
                    else effective_trigger
                )
                control_paths = tuple(
                    sorted(
                        set(plan.control_paths)
                        | {
                            path
                            for path in changed_control_paths
                            if _is_conftest_path(path)
                            and _scope_applies(path.rpartition("/")[0], test_path)
                        }
                        | ({plan.trigger} if plan.trigger in changed_control_paths else set())
                        | _package_init_paths(module, package_shape_paths)
                    )
                )
                dedupe = (module.split(".", 1)[0], after_root)
                if dedupe in seen:
                    index = seen[dedupe]
                    existing = hits[index]
                    related = tuple(
                        sorted(
                            {
                                *existing.related_evidence_paths,
                                existing.after_provider,
                                *existing.after_chain,
                                after_provider,
                                *package_chain,
                            }
                        )
                    )
                    controls = tuple(
                        sorted({*existing.control_paths, *control_paths})
                    )
                    if reportable and not existing.reportable:
                        hits[index] = SubjectShadow(
                            finding_path=finding_path,
                            module=module,
                            before_provider=before_provider,
                            after_provider=after_provider,
                            test_path=test_path,
                            trigger=effective_trigger,
                            after_chain=package_chain,
                            related_evidence_paths=related,
                            control_paths=controls,
                            reportable=True,
                        )
                    else:
                        hits[index] = replace(
                            existing,
                            related_evidence_paths=related,
                            control_paths=controls,
                        )
                    continue
                seen[dedupe] = len(hits)
                hits.append(
                    SubjectShadow(
                        finding_path=finding_path,
                        module=module,
                        before_provider=before_provider,
                        after_provider=after_provider,
                        test_path=test_path,
                        trigger=effective_trigger,
                        after_chain=package_chain,
                        control_paths=control_paths,
                        reportable=reportable,
                    )
                )
    return sorted(hits, key=lambda hit: (hit.finding_path, hit.module, hit.test_path))
