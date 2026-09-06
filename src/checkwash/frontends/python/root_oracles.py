"""Bounded projection for transparent repository-root equality helpers.

This is deliberately narrower than Python import or argument evaluation. A
two-parameter helper containing only ``assert actual == expected`` can retain
the actual call and expected literal at its caller. Merely inheriting the
helper's unbound parameters would hide an edited expected argument.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import replace

from checkwash.ir.astutil import dotted_name

MAX_ROOT_CALLS = 64


def _docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _plain_definition(node):
    if not isinstance(node, ast.FunctionDef):
        return False
    args = node.args
    return not (node.decorator_list or node.returns or getattr(node, "type_params", ())
                or args.defaults or any(a is not None for a in args.kw_defaults)
                or any(a.annotation for a in [*args.posonlyargs, *args.args, *args.kwonlyargs])
                or (args.vararg and args.vararg.annotation) or (args.kwarg and args.kwarg.annotation))


def _literal(node):
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def _actual_and_expected(operands):
    if len(operands) != 2:
        return None
    actuals = [n for n in operands if isinstance(n, ast.Call)]
    if len(actuals) != 1 or not all(isinstance(n, ast.Call) or _literal(n) for n in operands):
        return None
    actual = actuals[0]
    if not dotted_name(actual.func) or actual.keywords or not all(_literal(n) for n in actual.args):
        return None
    return actual, next(n for n in operands if n is not actual)


def _safe_caller(tree, local):
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _docstring(node):
            continue
        if not _plain_definition(node) or not node.name.startswith("test"):
            return False
        oracles = 0
        for statement in node.body:
            if isinstance(statement, ast.Pass) or _docstring(statement):
                continue
            operands = None
            if (isinstance(statement, ast.Assert) and statement.msg is None
                    and isinstance(statement.test, ast.Compare) and len(statement.test.ops) == 1
                    and isinstance(statement.test.ops[0], ast.Eq)):
                operands = [statement.test.left, *statement.test.comparators]
            elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                  and isinstance(statement.value.func, ast.Name) and statement.value.func.id == local
                  and not statement.value.keywords):
                operands = statement.value.args
            if operands is None or _actual_and_expected(operands) is None:
                return False
            oracles += 1
            if oracles > 1:
                return False
    return True


def root_caller_unchanged(before: bytes, after: bytes, module: str, local: str, original: str, unit: str):
    """Only the helper import and concrete oracle spelling may change.

    Expected literals remain available to the detector; comparing the rest
    of the module prevents changed imports or other code from acquiring new
    credit merely because the subject keeps the same spelling.
    """
    from checkwash.frontends.python.frontend import normalize_source

    def shape(source):
        tree = ast.parse(normalize_source(source))
        if not _safe_caller(tree, local):
            return None
        body = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
                node.names = [a for a in node.names if (a.asname or a.name, a.name) != (local, original)]
                if not node.names:
                    continue
            if isinstance(node, ast.FunctionDef) and node.name == unit:
                for index, statement in enumerate(node.body):
                    operands = None
                    if (isinstance(statement, ast.Assert) and statement.msg is None
                            and isinstance(statement.test, ast.Compare) and len(statement.test.ops) == 1
                            and isinstance(statement.test.ops[0], ast.Eq)):
                        operands = [statement.test.left, *statement.test.comparators]
                    elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                          and isinstance(statement.value.func, ast.Name) and statement.value.func.id == local
                          and not statement.value.keywords):
                        operands = statement.value.args
                    concrete = _actual_and_expected(operands) if operands is not None else None
                    if concrete is not None:
                        node.body[index] = ast.Assert(
                            test=ast.Compare(left=concrete[0], ops=[ast.Eq()], comparators=[ast.Constant(value=None)]),
                            msg=None,
                        )
            body.append(node)
        tree.body = body
        return ast.dump(tree, include_attributes=False)

    old, new = shape(before), shape(after)
    return old is not None and old == new


def _bindings(statements):
    """Module bindings, without confusing locals in a function with globals."""
    names = []
    pending = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.append(node.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(a.asname or a.name.split(".")[0] for a in node.names)
        pending.extend(ast.iter_child_nodes(node))
    return Counter(names)


def root_imports(source: bytes) -> dict[str, tuple[str, str]]:
    """Unshadowed top-level absolute, single-component from-imports only."""
    from checkwash.frontends.python.frontend import normalize_source

    tree = ast.parse(normalize_source(source))
    bindings = _bindings(tree.body)
    globals_written = {n for node in ast.walk(tree) if isinstance(node, ast.Global) for n in node.names}
    return {
        alias.asname or alias.name: (node.module, alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0
        and node.module and "." not in node.module
        for alias in node.names
        if alias.name != "*" and bindings[alias.asname or alias.name] == 1
        and (alias.asname or alias.name) not in globals_written
    }


def transparent_root_helpers(source: bytes):
    """Names whose definitions meet the exact projection contract."""
    from checkwash.frontends.python.frontend import normalize_source

    try:
        tree = ast.parse(normalize_source(source))
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return {}
    bindings = _bindings(tree.body)
    result = {}
    for definition in tree.body:
        if _docstring(definition):
            continue
        if (not isinstance(definition, ast.FunctionDef) or definition.name.startswith("test")
                or bindings[definition.name] != 1 or not _plain_definition(definition)):
            return {}
        args = definition.args
        params = [a.arg for a in [*args.posonlyargs, *args.args]]
        if len(params) != 2 or args.defaults or args.kwonlyargs or args.vararg or args.kwarg:
            return {}
        if len(definition.body) != 1 or not isinstance(definition.body[0], ast.Assert):
            return {}
        assertion = definition.body[0]
        compare = assertion.test
        if assertion.msg is not None or not isinstance(compare, ast.Compare) or len(compare.ops) != 1:
            return {}
        operands = [compare.left, *compare.comparators]
        if not isinstance(compare.ops[0], ast.Eq) or not all(isinstance(n, ast.Name) for n in operands):
            return {}
        if {n.id for n in operands} == set(params):
            result[definition.name] = (params, operands)
        else:
            return {}
    return result


def project_root_oracles(importer: bytes, helper: bytes, local: str, original: str):
    """Return caller-qualified assertions; unsupported shapes earn no credit.

    Accepted calls are direct statements of top-level test functions: one
    ordinary call with literal arguments, and one literal expected value,
    passed positionally to a transparent equality helper. No defaults,
    decorators, forwarding, coercions, control flow or local shadowing.
    """
    from checkwash.frontends.python.frontend import _Offsets, normalize_source, parse_python

    definition = transparent_root_helpers(helper).get(original)
    if definition is None:
        return {}
    params, operands = definition

    text = normalize_source(importer)
    tree = ast.parse(text)
    if not _safe_caller(tree, local):
        return {}
    offsets = _Offsets(text)
    result = {}

    for unit in tree.body:
        if not isinstance(unit, ast.FunctionDef) or not unit.name.startswith("test"):
            continue
        bound = {n.id for n in ast.walk(unit) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        bound.update(a.arg for a in [*unit.args.posonlyargs, *unit.args.args, *unit.args.kwonlyargs])
        bound.update(a.arg for a in (unit.args.vararg, unit.args.kwarg) if a is not None)
        if local in bound:
            continue
        sites = [n.value for n in unit.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name) and n.value.func.id == local]
        if len(sites) > MAX_ROOT_CALLS:
            continue
        inherited = []
        for site in sites:
            if len(site.args) != 2 or site.keywords or any(isinstance(n, ast.Starred) for n in site.args):
                continue
            concrete = _actual_and_expected(site.args)
            if concrete is None:
                continue
            actual = concrete[0]
            if any(isinstance(n, ast.Name) and n.id in bound for n in ast.walk(actual)):
                continue
            substitutions = dict(zip(params, site.args))
            expression = ast.Compare(left=substitutions[operands[0].id], ops=[ast.Eq()],
                                     comparators=[substitutions[operands[1].id]])
            synthetic = ("def test_projected():\n    assert " + ast.unparse(expression) + "\n").encode("utf-8")
            projected = parse_python(synthetic, collect_tests=True).units[0].side.assertions[0]
            inherited.append(replace(projected, text=offsets.seg(site), span=offsets.span(site), inherited=True))
        if inherited:
            result[unit.name] = inherited
    return result
