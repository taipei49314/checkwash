"""Project an inline transparent scalar-equality truthiness carrier.

Only a closed class with two field assignments and one equality return is
recognized. The actual value must be proved a built-in scalar by the strict,
unchanged production snapshot. This is deliberately not arbitrary __bool__
execution: custom equality results and dynamic attribute hooks earn nothing.
"""

from __future__ import annotations

import ast
from dataclasses import replace

from checkwash.change import EngineError
from checkwash.frontends.python.normalization import (
    _MAX_READS, _Unproved, _docstring, _plain_function, _production, _project,
    _return_function, _string_chain, _tree,
)
from checkwash.frontends.python.snapshot_context import inert_test_execution_context


def _carrier(node):
    if (node.bases or node.keywords or node.decorator_list or getattr(node, "type_params", ())
            or len(node.body) != 2 or any(not isinstance(n, ast.FunctionDef) for n in node.body)):
        raise _Unproved
    methods = {n.name: n for n in node.body}
    if set(methods) != {"__init__", "__bool__"}:
        raise _Unproved
    initializer, boolean = methods["__init__"], methods["__bool__"]
    params = _plain_function(initializer, 3)
    self_name, first, second = (p.arg for p in params)
    if len({self_name, first, second}) != 3 or len(initializer.body) != 2:
        raise _Unproved
    attributes = {}
    for assignment in initializer.body:
        if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Attribute)
                or not isinstance(assignment.targets[0].value, ast.Name)
                or assignment.targets[0].value.id != self_name
                or not isinstance(assignment.value, ast.Name)
                or assignment.value.id not in (first, second)
                or assignment.targets[0].attr.startswith("__")
                or assignment.targets[0].attr in attributes):
            raise _Unproved
        attributes[assignment.targets[0].attr] = assignment.value.id
    bool_self = _plain_function(boolean, 1)[0].arg
    if len(boolean.body) != 1 or not isinstance(boolean.body[0], ast.Return):
        raise _Unproved
    comparison = boolean.body[0].value
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq):
        raise _Unproved
    operands = [comparison.left, comparison.comparators[0]]
    if any(not isinstance(n, ast.Attribute) or not isinstance(n.value, ast.Name)
           or n.value.id != bool_self or n.attr not in attributes for n in operands):
        raise _Unproved
    if {attributes[n.attr] for n in operands} != {first, second}:
        raise _Unproved


def _closed_module(source):
    tree = _tree(source)
    occupied, imports, helpers, carriers, tests = set(), {}, {}, set(), {}
    for node in tree.body:
        if _docstring(node):
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                if name in occupied or alias.name == "*":
                    raise _Unproved
                occupied.add(name)
                imports[name] = (node.module, alias.name)
            continue
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef)) or node.name in occupied:
            raise _Unproved
        occupied.add(node.name)
        if isinstance(node, ast.ClassDef):
            _carrier(node)
            carriers.add(node.name)
        elif node.name.startswith("test"):
            _plain_function(node, 0)
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Assert) or node.body[0].msg is not None:
                raise _Unproved
            tests[node.name] = node.body[0]
        else:
            parameter, expression = _return_function(node)
            if not _string_chain(expression, parameter):
                raise _Unproved
            helpers[node.name] = (parameter, expression)
    if len(imports) != 1:
        raise _Unproved
    return imports, helpers, carriers, tests


def _scalar(node, imports, helpers, path, read, depth=0):
    if depth > 8:
        raise _Unproved
    if isinstance(node, ast.Constant):
        result = _project(node, {}, {})
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
          and len(node.args) == 1 and not node.keywords):
        if node.func.id in imports:
            argument = _project(node.args[0], {}, helpers)
            if not isinstance(argument, ast.Constant):
                raise _Unproved
            module, original = imports[node.func.id]
            parameter, expression = _production(module, original, path, read)
            result = _project(expression, {parameter: argument}, {})
        elif node.func.id in helpers:
            argument = _scalar(node.args[0], imports, helpers, path, read, depth + 1)
            parameter, expression = helpers[node.func.id]
            result = _project(expression, {parameter: argument}, {})
        else:
            raise _Unproved
    else:
        raise _Unproved
    if not isinstance(result, ast.Constant) or type(result.value) not in (str, int, bool, type(None)):
        raise _Unproved
    return result


def _project_side(path, source, parsed, read):
    from checkwash.frontends.python.frontend import _Offsets, _classify_assert_expr, normalize_source

    imports, helpers, carriers, tests = _closed_module(source)
    if not carriers:
        return
    projections = {}
    offsets = _Offsets(normalize_source(source))
    for name, assertion in tests.items():
        expression = assertion.test
        if (isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name)
                and expression.func.id in carriers and len(expression.args) == 2 and not expression.keywords):
            actual, expected = expression.args
            if not isinstance(actual, ast.Call) or not isinstance(expected, ast.Constant):
                raise _Unproved
            _scalar(actual, imports, helpers, path, read)
            _scalar(expected, imports, helpers, path, read)
            comparison = ast.Compare(left=actual, ops=[ast.Eq()], comparators=[expected])
            projections[name] = (offsets.span(assertion), _classify_assert_expr(comparison, offsets))
        elif (isinstance(expression, ast.Compare) and len(expression.ops) == 1
              and isinstance(expression.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot))):
            # Companion assertions must not be able to mutate the carrier or
            # production binding while appearing to be ordinary tests.
            _scalar(expression.left, imports, helpers, path, read)
            _scalar(expression.comparators[0], imports, helpers, path, read)
        else:
            raise _Unproved
    for unit in parsed.units:
        if unit.qualname not in projections:
            continue
        span, classified = projections[unit.qualname]
        unit.side.assertions = [
            replace(assertion, form=classified.form, strength=classified.strength,
                    left=classified.left, right_literal=classified.right_literal,
                    right_value=classified.right_value, positive=classified.positive,
                    left_names=classified.left_names, right_depends_on=classified.right_names)
            if assertion.span == span and not assertion.inherited and assertion.form == "truthy"
            else assertion
            for assertion in unit.side.assertions
        ]


def project_truthiness_oracles(path, before_parsed, after_parsed, raw_by_path, root_reader, root_searcher):
    """Resolve the two source sides independently; unsupported sides stay as-is."""
    before, after = raw_by_path[path]
    if not any(source and b"__bool__" in source for source in (before, after)):
        return
    if any(other != path and old != new for other, (old, new) in raw_by_path.items()):
        return
    cache = {}

    def read(candidate):
        if candidate not in cache:
            if candidate in raw_by_path:
                old, new = raw_by_path[candidate]
                if old != new:
                    raise _Unproved
                cache[candidate] = new
            elif root_reader is None or len(cache) >= _MAX_READS:
                raise _Unproved
            else:
                cache[candidate] = root_reader(candidate)
            if cache[candidate] is not None and not isinstance(cache[candidate], bytes):
                raise EngineError("strict truthiness-oracle reader returned invalid source bytes")
        return cache[candidate]

    try:
        if not inert_test_execution_context(path, read, root_searcher):
            return
    except _Unproved:
        return
    for source, parsed in ((before, before_parsed), (after, after_parsed)):
        if source is None or parsed is None or not parsed.parse_ok:
            continue
        try:
            _project_side(path, source, parsed, read)
        except (_Unproved, RecursionError, MemoryError):
            pass
