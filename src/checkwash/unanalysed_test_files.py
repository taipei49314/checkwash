"""Changed test-shaped files outside the Python and JS/TS test parse gates (0.13, B6).

Reporting evidence only: surfaced on stderr, the terminal report, and SARIF
`toolExecutionNotifications`. Never alters IR, findings, verdicts, exit codes,
`--format json` stdout, `--emit-ir`, `--format hook-json`, or `hook pre-tool-use`.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
import re
from typing import TYPE_CHECKING
import unicodedata

from checkwash.change import FileChange
from checkwash.frontends.javascript.bindings import Bindings
from checkwash.frontends.javascript.frontend import _code_positions, parse_javascript
from checkwash.frontends.javascript.paths import _JEST_EXTENSIONS, is_js_test_file
from checkwash.frontends.python.frontend import normalize_source
from checkwash.frontends.python.syntax import parse_module
from checkwash.gitio.snapshot import MAX_SOURCE_BYTES
from checkwash.roles import collectable, is_artifact, is_test_support_path

if TYPE_CHECKING:
    from checkwash.config import Config

_TEST_DIRS = frozenset({
    "test",
    "tests",
    "__test__",
    "__tests__",
    "spec",
    "specs",
    "e2e",
    "unit_tests",
    "integration_tests",
    "functional_tests",
})

_JS_TEST_DIRS = _TEST_DIRS | {"cypress", "playwright"}

_JS_SUPPORT_DIRS = frozenset({
    "__mocks__",
    "__fixtures__",
    "__testfixtures__",
    "fixtures",
    "mocks",
})

_VENDOR_SEGMENTS = frozenset({"site-packages", "dist-packages"})

_SUPERVISED_NON_TEST_ROLES = frozenset({
    "guardrail",
    "ci",
    "snapshot",
    "lockfile",
    "conftest",
})

_PY_NON_TEST_BASENAMES = frozenset({
    "__init__.py",
    "__main__.py",
    "conftest.py",
    "setup.py",
    "manage.py",
    "fabfile.py",
    "noxfile.py",
    "tasks.py",
})

_PY_HELPER_TEST_PREFIX_EXCLUSIONS = frozenset({
    "testing.py",
    "testutils.py",
    "testhelpers.py",
    "testsupport.py",
})

_PY_TEST_IMPORT_ROOTS = frozenset({"pytest", "unittest", "hypothesis"})

_PY_TESTCASE_SUFFIXES = (
    "TestCase",
    "TestSuite",
)

_PY_TEST_CLASS_SUFFIXES = (
    "Tests",
    "Checks",
    "Suite",
    "Mixin",
    "Base",
)

_PY_FALLBACK_TEST_RE = re.compile(
    r"(?m)^[ \t]*(?:async[ \t]+)?def[ \t]+test(?:_|\b)"
    r"|^[ \t]*class[ \t]+[A-Za-z_]\w*\([^)\n]*TestCase\b"
)
_PY_FALLBACK_TESTCASE_RE = re.compile(
    r"(?m)^[ \t]*class[ \t]+[A-Za-z_]\w*\([^)\n]*TestCase\b"
)

_JS_DOTTED_TEST_SUFFIXES = (
    ".unit",
    ".integration",
    ".int",
    ".e2e",
    ".cy",
    ".tests",
    ".specs",
    ".test",
    ".spec",
    ".ava",
    ".tap",
    ".playwright",
    ".pw",
)

_JS_CAMEL_TEST_SUFFIXES = ("Spec", "Specs", "Tests")

_JS_CANDIDATE_BYTES_RE = re.compile(
    rb"(?<![\w$])(?:x?describe|fdescribe|x?context|suite|x?test|x?it|fit|specify)(?![\w$])"
    rb"|@playwright/test|\bcypress\b|\bcy\."
)

_JS_RUNNER_BYTES_RE = re.compile(
    rb"@playwright/test|node:test|vitest|@jest/globals|bun:test"
    rb"|(?<![\w$])(?:ava|tap|uvu|qunit|tape|mocha|jasmine|cypress|Deno)(?![\w$])"
)

_JS_MASKED_CALL_RE = re.compile(
    r"(?<![\w$.])(?:x?describe|fdescribe|x?context|suite|x?test|x?it|fit|specify)\s*(?:\.\s*\w+\s*)*\("
)

_JS_METHOD_DECL_TAIL_RE = re.compile(r"[A-Za-z0-9_$.,=\s]*+\)\s*+\{")

_JS_RUNNER_SPECIFIER_RE = re.compile(
    r"""(?:\b(?:from|import)\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)(['"])"""
    r"""(?:@playwright/test|node:test|vitest|@jest/globals|bun:test|ava|tap|uvu|qunit|tape|mocha|jasmine|cypress)"""
    r"""(?:/[^'"]*)?\1"""
    r"""|\bDeno\s*\.\s*test\b"""
)


def _shown(text: str) -> str:
    """Keep printable paths verbatim; escape control and format characters (#346)."""
    if not text.isprintable() or any(unicodedata.category(ch) == "Cf" for ch in text):
        return repr(text)
    return text


def _listed(items: list[str], shown: int = 4) -> str:
    head = ", ".join(items[:shown])
    return head if len(items) <= shown else f"{head} and {len(items) - shown} more"


def unanalysed_test_note(paths: Iterable[str]) -> str:
    """Format the single-line summary note for unanalysed test-shaped files."""
    ordered = sorted({path.replace("\\", "/") for path in paths})
    count = len(ordered)
    noun = "test-shaped file" if count == 1 else "test-shaped files"
    return f"analysis incomplete: {count} {noun} not analysed: {_listed([_shown(p) for p in ordered])}"


def _terminal_name(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Subscript):
        return _terminal_name(expr.value)
    return ""


def _is_test_def_name(name: str) -> bool:
    return name == "test" or name.startswith("test_")


def _dunder_test_bool(body: list[ast.stmt]) -> bool | None:
    """Return True/False when `__test__` is assigned in `body`, or None if absent."""
    result: bool | None = None
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__test__" for t in targets):
            continue
        if isinstance(value, ast.Constant):
            result = bool(value.value)
        elif isinstance(value, ast.Dict):
            result = bool(value.keys or value.values)
        elif isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            result = bool(value.elts)
        else:
            result = True
    return result


def _has_test_decorator(decorators: list[ast.expr]) -> bool:
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        parts: list[str] = []
        cur = target
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        if parts and parts[0] in ("pytest", "unittest"):
            return True
    return False


def _body_has_oracle_shape(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr.startswith("assert") or node.func.attr in ("skipTest", "fail", "raises", "skip", "xfail"):
                return True
    return False


def _class_has_tests(cls: ast.ClassDef, *, in_test_scope: bool, has_test_import: bool) -> bool:
    if any(_terminal_name(base).endswith(_PY_TESTCASE_SUFFIXES) for base in cls.bases):
        return True
    dunder_test = _dunder_test_bool(cls.body)
    if (in_test_scope and dunder_test is True) or _has_test_decorator(cls.decorator_list):
        return True
    opted_out = dunder_test is False
    class_looks_test_named = not opted_out and (
        cls.name.startswith("Test") or cls.name.endswith(_PY_TEST_CLASS_SUFFIXES)
    )
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_def_name(item.name):
            if opted_out:
                if _has_test_decorator(item.decorator_list) or _body_has_oracle_shape(item):
                    return True
            elif (
                in_test_scope
                or has_test_import
                or class_looks_test_named
                or _has_test_decorator(item.decorator_list)
                or _body_has_oracle_shape(item)
            ):
                return True
        elif isinstance(item, ast.ClassDef) and _class_has_tests(
            item, in_test_scope=in_test_scope, has_test_import=has_test_import,
        ):
            return True
    return False


def _python_side_has_tests(data: bytes | None, *, in_test_scope: bool) -> bool:
    if not data or len(data) > MAX_SOURCE_BYTES or b"\x00" in data:
        return False
    if b"test" not in data and b"Test" not in data:
        return False
    text = normalize_source(data)
    try:
        tree = parse_module(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        pattern = _PY_FALLBACK_TEST_RE if in_test_scope else _PY_FALLBACK_TESTCASE_RE
        return bool(pattern.search(text))

    has_test_import = False
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            if any(alias.name.split(".", 1)[0] in _PY_TEST_IMPORT_ROOTS for alias in stmt.names):
                has_test_import = True
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            if stmt.module.split(".", 1)[0] in _PY_TEST_IMPORT_ROOTS:
                has_test_import = True

    dunder_test = _dunder_test_bool(tree.body)
    if in_test_scope and dunder_test is True:
        return True
    opted_out = dunder_test is False

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_def_name(stmt.name):
            if opted_out:
                if _has_test_decorator(stmt.decorator_list) or _body_has_oracle_shape(stmt):
                    return True
            elif in_test_scope or has_test_import or _has_test_decorator(stmt.decorator_list):
                return True
        elif isinstance(stmt, ast.ClassDef) and _class_has_tests(
            stmt, in_test_scope=in_test_scope, has_test_import=has_test_import,
        ):
            return True
    return False


def _is_python_test_named(candidate: str, *, role: str) -> bool:
    *dirs, name = candidate.split("/")
    lname = name.lower()
    if not lname.endswith(".py") or lname in _PY_NON_TEST_BASENAMES:
        return False
    if lname.startswith("test_") or lname.endswith("_test.py"):
        return True
    in_test_dir = role == "test" or any(d.lower() in _TEST_DIRS for d in dirs)
    if not in_test_dir:
        return False
    if lname == "tests.py" or lname.endswith(("_tests.py", "_spec.py", "_specs.py")):
        return True
    if lname.startswith("test") and lname not in _PY_HELPER_TEST_PREFIX_EXCLUSIONS:
        return True
    return lname.startswith(("spec_", "check_")) or lname.endswith(("_check.py", "_checks.py"))


def _is_js_config_or_setup(lstem: str) -> bool:
    return (
        lstem.endswith((".config", ".conf", ".setup"))
        or lstem in ("setup", "setuptests", "globalsetup", "globalteardown", "global-setup", "global-teardown")
        or lstem.startswith(".mocharc")
    )


def _is_js_test_named(candidate: str) -> bool:
    *_dirs, name = candidate.split("/")
    lname = name.lower()
    if lname.endswith((".d.ts", ".d.mts", ".d.cts")):
        return False
    stem, sep, ext = name.rpartition(".")
    if not sep or ext.lower() not in _JEST_EXTENSIONS:
        return False
    lstem = stem.lower()
    if _is_js_config_or_setup(lstem):
        return False
    if lstem.endswith(_JS_DOTTED_TEST_SUFFIXES):
        return True
    if (
        lstem in ("test", "tests", "spec", "specs")
        or lstem.startswith(("test_", "test-", "spec_", "spec-"))
        or lstem.endswith(("_test", "-test", "_tests", "-tests", "_spec", "-spec", "_specs", "-specs"))
    ):
        return True
    for suffix in _JS_CAMEL_TEST_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            prev = stem[-len(suffix) - 1]
            if prev.isalnum() or prev in "_$":
                return True
    return False


def _has_js_test_call(masked: str) -> bool:
    for match in _JS_MASKED_CALL_RE.finditer(masked):
        idx = match.start() - 1
        while idx >= 0 and masked[idx].isspace():
            idx -= 1
        if idx >= 0 and masked[idx] == ".":
            continue
        if (
            idx >= 7
            and masked[idx - 7 : idx + 1] == "function"
            and (idx == 7 or not (masked[idx - 8].isalnum() or masked[idx - 8] in "_$"))
        ):
            continue
        if _JS_METHOD_DECL_TAIL_RE.match(masked, match.end()):
            continue
        return True
    return False


def _js_side_has_tests(data: bytes | None, *, in_js_test_dir: bool) -> bool:
    if not data or len(data) > MAX_SOURCE_BYTES or b"\x00" in data:
        return False
    if not in_js_test_dir:
        if not _JS_RUNNER_BYTES_RE.search(data):
            return False
    elif not _JS_CANDIDATE_BYTES_RE.search(data) and not _JS_RUNNER_BYTES_RE.search(data):
        return False
    text = normalize_source(data)
    code = _code_positions(text)
    code_with_strings = _code_positions(text, keep_strings=True)
    masked_with_strings = "".join(
        ch if keep or ch == "\n" else " " for ch, keep in zip(text, code_with_strings)
    )
    has_runner_import = any(
        code[m.start()] for m in _JS_RUNNER_SPECIFIER_RE.finditer(masked_with_strings)
    )
    if in_js_test_dir:
        if has_runner_import:
            return True
        bindings = Bindings(text, code, code_with_strings)
        return _has_js_test_call(bindings.masked)
    if not has_runner_import:
        return False
    return parse_javascript(data).declares_tests


def _is_side_unanalysed_test(
    side_path: str,
    sides: tuple[bytes | None, ...],
    *,
    role: str,
    is_python: bool,
    is_js_test: bool,
    judged_test: bool,
    collect: bool,
    parse_ok: bool,
    status: str,
) -> bool:
    if is_artifact(side_path):
        return False
    segments = side_path.split("/")
    if any(seg.lower() in _VENDOR_SEGMENTS for seg in segments[:-1]):
        return False
    if role in _SUPERVISED_NON_TEST_ROLES or collect or is_js_test:
        return False
    # Exact `.py` matches `engine_ir_files.py:290` (`TEST_FILE_UNPARSEABLE`); `.PY`
    # paths are not reported there and fall through to `lower_name.endswith(".py")`.
    if is_python and judged_test and not parse_ok and status != "deleted":
        return False

    lower_name = segments[-1].lower()
    if lower_name.endswith(".py"):
        if _is_python_test_named(side_path, role=role):
            return True
        in_test_scope = (
            role == "test"
            or any(d.lower() in _TEST_DIRS for d in segments[:-1])
            or lower_name == "tests.py"
            or lower_name.endswith(("_tests.py", "_spec.py", "_specs.py"))
        )
        return any(_python_side_has_tests(side, in_test_scope=in_test_scope) for side in sides)

    if lower_name.endswith((".d.ts", ".d.mts", ".d.cts")):
        return False
    _stem, sep, ext = segments[-1].rpartition(".")
    if not (sep and ext.lower() in _JEST_EXTENSIONS):
        return False
    if _is_js_test_named(side_path):
        return True

    c_dirs = [d.lower() for d in segments[:-1]]
    in_js_test_dir = not any(d in _JS_SUPPORT_DIRS for d in c_dirs) and (
        role == "test" or any(d in _JS_TEST_DIRS for d in c_dirs)
    )
    return any(_js_side_has_tests(side, in_js_test_dir=in_js_test_dir) for side in sides)


def unanalysed_test_paths(
    path: str,
    change: FileChange,
    *,
    config: Config | None = None,
    role: str,
    is_python: bool,
    is_js_test: bool,
    judged_test: bool,
    collect: bool,
    parse_ok: bool,
) -> list[str]:
    """Return unanalysed test-shaped path(s) for `change` (handling unsplit renames per side)."""
    if change.synthetic is not None or collect or is_js_test:
        return []
    # Exact `.py` matches `engine_ir_files.py:290` (`TEST_FILE_UNPARSEABLE`).
    if is_python and judged_test and not parse_ok and change.status != "deleted":
        return []

    normalized = path.replace("\\", "/")
    old_normalized = change.old_path.replace("\\", "/") if change.old_path else None
    if not old_normalized or old_normalized == normalized:
        if _is_side_unanalysed_test(
            normalized,
            (change.before, change.after),
            role=role,
            is_python=is_python,
            is_js_test=is_js_test,
            judged_test=judged_test,
            collect=collect,
            parse_ok=parse_ok,
            status=change.status,
        ):
            return [normalized]
        return []

    if _is_side_unanalysed_test(
        normalized,
        (change.after,),
        role=role,
        is_python=is_python,
        is_js_test=is_js_test,
        judged_test=judged_test,
        collect=collect,
        parse_ok=parse_ok,
        status=change.status,
    ):
        return [normalized]

    old_role = config.role_of(old_normalized) if config is not None else "prod"
    old_is_js_test = is_js_test_file(old_normalized, change.before)
    if old_role == "prod" and (old_is_js_test or is_test_support_path(old_normalized)):
        old_role = "test"
    old_is_python = old_normalized.endswith(".py")
    old_judged_test = old_role == "test" or old_is_js_test or (old_is_python and collectable(old_normalized))
    old_collect = old_is_python and (old_role == "conftest" or (old_judged_test and collectable(old_normalized)))
    if _is_side_unanalysed_test(
        old_normalized,
        (change.before,),
        role=old_role,
        is_python=old_is_python,
        is_js_test=old_is_js_test,
        judged_test=old_judged_test,
        collect=old_collect,
        parse_ok=True,
        status="deleted",
    ):
        return [old_normalized]
    return []


def is_unanalysed_test_file(
    path: str,
    change: FileChange,
    *,
    config: Config | None = None,
    role: str,
    is_python: bool,
    is_js_test: bool,
    judged_test: bool,
    collect: bool,
    parse_ok: bool,
) -> bool:
    """Return True when `change` looks like a Python or JS/TS test file CheckWash did not analyse."""
    return bool(
        unanalysed_test_paths(
            path,
            change,
            config=config,
            role=role,
            is_python=is_python,
            is_js_test=is_js_test,
            judged_test=judged_test,
            collect=collect,
            parse_ok=parse_ok,
        )
    )
