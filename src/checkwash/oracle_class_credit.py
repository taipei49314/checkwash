"""Closed source proof for moving a plain pytest function into a plain class.

The class receiver is removable only after the entire module, startup and all
imported calls have a side-bound no-effects proof. A syntactic unused ``self``
or a compatibility marker alone is never a certificate. Subject code is never
executed. This deliberately does not prove the original #263 fixture, whose
producer and startup snapshot are unavailable.
"""
from __future__ import annotations

import ast
import configparser
import copy
import hashlib
import json
from pathlib import PurePosixPath

from checkwash.change import EngineError
from checkwash.frontends.python.oracle_purity import pure_imported_calls
from checkwash.ir.astutil import stable_dump
from checkwash.oracle_fixture_credit import (
    _Paths, _Reader, _Unavailable, _bind, _compiler_bindings, _definition,
    _expression, _inert, _inventory, _literal, _no_parameters,
    _ordinary_binding, _path, _startup, _tree,
)
from checkwash.roles import collectable


def _false_marker(node):
    """A canonical skipif call whose safe string expression is always false."""
    if (not isinstance(node, ast.Call) or ast.unparse(node.func) != "pytest.mark.skipif"
            or len(node.args) != 1 or not isinstance(node.args[0], ast.Constant)
            or type(node.args[0].value) is not str or len(node.args[0].value) > 512
            or len(node.keywords) > 1):
        return False
    if any(keyword.arg != "reason" or not isinstance(keyword.value, ast.Constant)
           or type(keyword.value.value) is not str for keyword in node.keywords):
        return False
    try:
        condition = ast.parse(node.args[0].value, mode="eval").body
    except (SyntaxError, ValueError):
        return False

    if isinstance(condition, ast.Constant):
        return condition.value is False
    if not isinstance(condition, ast.Compare) or len(condition.ops) != 1:
        return False
    left, right, operator = condition.left, condition.comparators[0], condition.ops[0]

    def version(part):
        return (isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name)
                and part.value.id == "sys" and part.attr == "version_info")

    if version(right) and isinstance(operator, (ast.Gt, ast.GtE)):
        left, right = right, left
    elif not isinstance(operator, (ast.Lt, ast.LtE)):
        return False
    if (not version(left) or not isinstance(right, ast.Tuple) or not 1 <= len(right.elts) <= 3
            or not all(isinstance(item, ast.Constant) and type(item.value) is int and item.value >= 0
                       for item in right.elts)):
        return False
    # SPEC's supported domain starts at Python 3.11. VersionInfo's complete
    # tuple has additional fields after patch; it is strictly greater than
    # every equal 1..3-item prefix. Thus both < and <= are false for a bound
    # <= (3, 11, 0), including (3, 11). This is an interval/prefix proof, not
    # sampling the finite compatibility environment matrix. Patch intervals,
    # future minors, arbitrary booleans and other comparisons stay unknown.
    bound = tuple(item.value for item in right.elts)
    return bound <= (3, 11, 0)


def _function(node, *, method):
    if (not isinstance(node, ast.FunctionDef) or not node.name.startswith("test")
            or not _ordinary_binding(node.name) or node.decorator_list or node.returns is not None
            or getattr(node, "type_params", ())):
        return False
    args = node.args
    if not method:
        return _no_parameters(args)
    return (not (args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
                 or args.defaults or args.kw_defaults)
            and len(args.args) == 1 and args.args[0].arg == "self"
            and args.args[0].annotation is None)


def _module(source, tree, *, path, read):
    if not _compiler_bindings(tree):
        return None
    imports, bound, marks, units = {}, set(), set(), {}
    framework = False
    for statement in tree.body:
        if _inert(statement):
            continue
        if isinstance(statement, ast.Import):
            if (framework or len(statement.names) != 1 or statement.names[0].name != "pytest"
                    or statement.names[0].asname is not None or "pytest" in bound):
                return None
            framework = True
            bound.add("pytest")
            continue
        if isinstance(statement, ast.ImportFrom):
            if (statement.level or not statement.module
                    or not all(part.isidentifier() for part in statement.module.split("."))):
                return None
            for alias in statement.names:
                name = alias.asname or alias.name
                if (not alias.name.isidentifier() or not _ordinary_binding(name)
                        or name in bound or name in {"self", "cls", "sys"}):
                    return None
                bound.add(name)
                imports[name] = (statement.module, alias.name)
            continue
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name) and framework
                and _ordinary_binding(statement.targets[0].id)
                and statement.targets[0].id not in bound and _false_marker(statement.value)):
            name = statement.targets[0].id
            marks.add(name)
            bound.add(name)
            continue
        if _function(statement, method=False):
            name = statement.name
            if name in bound:
                return None
            bound.add(name)
            units[name] = statement
            continue
        if (not isinstance(statement, ast.ClassDef) or not statement.name.startswith("Test")
                or not statement.name.isidentifier() or statement.name in bound
                or statement.bases or statement.keywords or statement.decorator_list
                or getattr(statement, "type_params", ())):
            return None
        bound.add(statement.name)
        class_names = set()
        for item in statement.body:
            if _inert(item):
                continue
            if (isinstance(item, ast.Assign) and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name) and item.targets[0].id == "pytestmark"
                    and "pytestmark" not in class_names and framework
                    and isinstance(item.value, ast.Name) and item.value.id in marks):
                class_names.add("pytestmark")
                continue
            if not _function(item, method=True) or item.name in class_names:
                return None
            class_names.add(item.name)
            units[statement.name + "." + item.name] = item

    # Validate every import, not merely calls reached by selected assertions.
    # The module grammar forbids later rebinding and all unproved execution.
    for name in sorted(imports):
        synthetic = ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[], keywords=[])
        if not pure_imported_calls(source, [synthetic], path=path, read=read, result_proof=_definition):
            return None
    per_unit = {}
    for name, function in sorted(units.items()):
        calls = []
        for statement in function.body:
            if _inert(statement):
                continue
            if (not isinstance(statement, ast.Assert) or not _expression(statement.test, imports, calls)
                    or statement.msg is not None and not _literal(statement.msg)):
                return None
        if not calls:
            continue  # no vacuous imported-producer proof.
        bindings = []

        def result_proof(data, target, call):
            binding = _bind(data, target, call)
            if binding is None:
                return False
            bindings.append((call.func.id, imports[call.func.id], binding))
            return True

        if not pure_imported_calls(source, calls, path=path, read=read, result_proof=result_proof):
            return None
        declaration = copy.deepcopy(function)
        if "." in name:
            declaration.args.args = []  # receiver is unused in the closed assertion grammar.
        for part in ast.walk(declaration):
            if "type_params" in part._fields and not getattr(part, "type_params", ()):
                part._fields = tuple(field for field in part._fields if field != "type_params")
        per_unit[name] = (function, stable_dump(declaration), bindings)
    return per_unit


def prove_plain_class_units(source, tree, functions, *, path, read, search, path_lister):
    """Return side-bound complete-unit certificates under closed file authority.

    Only ordinary classes and a proven always-false string skipif are admitted.
    All callers, producers, initializers, bootstrap and config paths are checked
    independently on each side. No arbitrary class/self/decorator is erased.
    """
    try:
        path = _path(path)
        if (type(functions) is not dict or not functions or len(functions) > 128
                or not callable(read) or not callable(search) or not callable(path_lister)
                or not collectable(path) or stable_dump(_tree(source)) != stable_dump(tree)):
            return {}
        inventory = _inventory(search)
        paths = _Paths(path_lister)
        python_paths = {candidate for candidate in paths.files if candidate.endswith(".py")}
        if path not in inventory or not inventory <= python_paths:
            return {}
        bounded = _Reader(read, paths, path, source)
        for candidate in sorted(python_paths):
            if bool(bounded(candidate)) != (candidate in inventory):
                return {}
        if not _startup(path, python_paths, bounded):
            return {}
        selected = _module(source, tree, path=path, read=bounded)
        if selected is None:
            return {}
        consumers = {candidate for candidate in python_paths if collectable(candidate)}
        if len({PurePosixPath(candidate).name for candidate in consumers}) != len(consumers):
            return {}
        for candidate in sorted(consumers - {path}):
            data = bounded(candidate)
            if data is None or _module(data, _tree(data), path=candidate, read=bounded) is None:
                return {}
        identities = bounded.identities(consumers)
        certificates = {}
        for name, (function, declaration, bindings) in selected.items():
            if functions.get(name) is not function:
                continue
            payload = ("closed-plain-pytest-class-unit-v1", declaration, bindings, identities)
            certificates[name] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return certificates
    except (_Unavailable, EngineError, OSError, ValueError, TypeError, SyntaxError,
            UnicodeError, RecursionError, MemoryError, configparser.Error):
        return {}
