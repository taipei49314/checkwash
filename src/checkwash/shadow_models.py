"""Shared data models, constants, and path primitives for runtime shadow detection."""

from __future__ import annotations

import ast
import posixpath
import re
import shlex
import sys
from dataclasses import dataclass
from typing import Any, Iterable

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


def _live_shadow_attr(name: str, default: Any) -> Any:
    """Resolve an attribute through ``checkwash.shadow`` when loaded so monkeypatches apply."""

    module = sys.modules.get("checkwash.shadow")
    if module is None:
        return default
    return getattr(module, name, default)


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
    # production repair. This matters for supported controls whose role is
    # still `prod` (notably a nested config such as `sub/pytest.ini`).
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


@dataclass(frozen=True)
class _FixtureBinding:
    imports: frozenset[str]
    dependencies: frozenset[str]
    autouse: bool = False


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _join(root: str, rel: str) -> str:
    return f"{root.rstrip('/')}/{rel}" if root else rel


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
