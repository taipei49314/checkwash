"""Additive subject-wrapper evidence across a literal parameter table.

Unlike concrete-table precision, this pass does not replace parsed units or
grant any equivalence credit. It joins a bounded old concrete comparison to
an arriving literal row only when callee, raw input, operator and expectation
match, and the new subject adds one recognized wrapper. Existing alignment,
compensation and severity remain independent of these source-backed events.
"""

from __future__ import annotations

import ast
import copy
from collections import Counter
from dataclasses import dataclass

from checkwash.frontends.python.frontend import _Offsets, normalize_source
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.frontends.python.table_oracles import (
    MAX_AST_NODES, MAX_CASES, MAX_SOURCE_BYTES, _Substitute, _args, _literal,
    _pytest_unshadowed, _rows,
)
from checkwash.ir.astutil import argument_wraps, dotted_name, expr_wraps


class _Unsupported(Exception):
    pass


@dataclass
class _Comparison:
    subject: ast.AST
    expected: ast.AST
    operator: str
    unit: str
    text: str
    span: tuple[int, int]


def _call(node, imports):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in imports and all(_literal(a) for a in node.args)
            and all(k.arg is not None and _literal(k.value) for k in node.keywords))


def _fold(node):
    """Only the fixed literal-str alphanumeric-filter plus lower spelling."""
    if (not isinstance(node, ast.Call) or node.args or node.keywords
            or not isinstance(node.func, ast.Attribute) or node.func.attr != "lower"):
        return False
    join = node.func.value
    if (not isinstance(join, ast.Call) or len(join.args) != 1 or join.keywords
            or not isinstance(join.func, ast.Attribute) or join.func.attr != "join"
            or not isinstance(join.func.value, ast.Constant) or join.func.value.value != ""):
        return False
    generator = join.args[0]
    if not isinstance(generator, ast.GeneratorExp) or len(generator.generators) != 1:
        return False
    clause = generator.generators[0]
    if (clause.is_async or not isinstance(clause.target, ast.Name)
            or not isinstance(clause.iter, ast.Constant) or type(clause.iter.value) is not str
            or not isinstance(generator.elt, ast.Name) or generator.elt.id != clause.target.id
            or len(clause.ifs) != 1):
        return False
    condition = clause.ifs[0]
    return (isinstance(condition, ast.Call) and not condition.args and not condition.keywords
            and isinstance(condition.func, ast.Attribute) and condition.func.attr == "isalnum"
            and isinstance(condition.func.value, ast.Name) and condition.func.value.id == clause.target.id)


def _wrapped(node, imports):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "abs" and "abs" not in imports
            and len(node.args) == 1 and not node.keywords and _call(node.args[0], imports)):
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in imports
            and sum(_fold(a) for a in node.args) == 1
            and all(_literal(a) or _fold(a) for a in node.args)
            and all(k.arg is not None and _literal(k.value) for k in node.keywords))


def _comparison(assertion, original, unit, offsets, imports, *, after):
    if not isinstance(assertion, ast.Assert) or assertion.msg is not None:
        raise _Unsupported
    expression = assertion.test
    if (not isinstance(expression, ast.Compare) or len(expression.ops) != 1
            or not isinstance(expression.ops[0], (ast.Eq, ast.Is))
            or not _literal(expression.comparators[0])):
        raise _Unsupported
    expected = expression.comparators[0]
    if isinstance(expression.ops[0], ast.Is) and not (
            isinstance(expected, ast.Constant) and type(expected.value) in (bool, type(None))):
        raise _Unsupported
    if not (_call(expression.left, imports) or (after and _wrapped(expression.left, imports))):
        raise _Unsupported
    return _Comparison(expression.left, expected, type(expression.ops[0]).__name__, unit,
                       offsets.seg(original), offsets.span(original))


def _module(source, *, after):
    if len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported
    text = normalize_source(source)
    tree, offsets = ast.parse(text), _Offsets(text)
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise _Unsupported
    occupied, imports, functions, helpers = set(), {}, [], {}
    pytest = False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if isinstance(node, ast.ImportFrom) and not functions and not node.level and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                if name in occupied or alias.name == "*" or name in ("pytest", "abs"):
                    raise _Unsupported
                imports[name] = (node.module, alias.name)
                occupied.add(name)
        elif (isinstance(node, ast.Import) and not functions and len(node.names) == 1
              and node.names[0].name == "pytest" and not node.names[0].asname and "pytest" not in occupied):
            pytest = True
            occupied.add("pytest")
        elif isinstance(node, ast.FunctionDef) and node.name not in occupied and node.name != "abs":
            occupied.add(node.name)
            functions.append(node)
        else:
            raise _Unsupported
    if not imports:
        raise _Unsupported
    for function in functions:
        if function.name.startswith("test"):
            continue
        args = _args(function)
        if (after or args is None or function.decorator_list or len(function.body) != 1
                or not isinstance(function.body[0], ast.Assert)):
            raise _Unsupported
        uses = Counter(n.id for n in ast.walk(function.body[0]) if isinstance(n, ast.Name) and n.id in args)
        if any(count > 1 for count in uses.values()):
            raise _Unsupported
        helpers[function.name] = (args, function.body[0])
    result = []
    table_seen = False
    for function in functions:
        if function.name in helpers:
            continue
        args = _args(function)
        if args is None:
            raise _Unsupported
        if not after:
            if args or function.decorator_list:
                raise _Unsupported
            for statement in function.body:
                assertion = statement
                if (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Name) and statement.value.func.id in helpers):
                    call = statement.value
                    params, assertion = helpers[call.func.id]
                    if call.keywords or len(params) != len(call.args) or not all(_literal(a) for a in call.args):
                        raise _Unsupported
                    assertion = _Substitute(dict(zip(params, call.args))).visit(copy.deepcopy(assertion))
                result.append(_comparison(assertion, statement, function.name, offsets, imports, after=False))
        else:
            if not pytest or len(function.decorator_list) != 1:
                raise _Unsupported
            decorator = function.decorator_list[0]
            if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.mark.parametrize"
                    or len(decorator.args) != 2 or decorator.keywords
                    or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str):
                raise _Unsupported
            columns = [name.strip() for name in decorator.args[0].value.split(",")]
            if not args or len(columns) != len(set(columns)) or set(columns) != set(args):
                raise _Unsupported
            rows = _rows(decorator.args[1], columns, unpack=len(columns) != 1)
            if rows is None:
                raise _Unsupported
            body, local = function.body, {}
            if len(body) == 2 and isinstance(body[0], ast.Assign):
                assignment = body[0]
                if (len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)
                        or assignment.targets[0].id in occupied | set(args)):
                    raise _Unsupported
                local[assignment.targets[0].id] = assignment.value
                body = body[1:]
            if len(body) != 1 or not isinstance(body[0], ast.Assert):
                raise _Unsupported
            # A generator's bound name must never be substituted as a row
            # variable. Rebinding and every additional assignment stay opaque.
            if any(isinstance(n, ast.comprehension) and any(
                    isinstance(target, ast.Name) and target.id in set(args) | local.keys()
                    for target in ast.walk(n.target)) for n in ast.walk(function)):
                raise _Unsupported
            template = _Substitute(local).visit(copy.deepcopy(body[0]))
            uses = Counter(n.id for n in ast.walk(template) if isinstance(n, ast.Name) and n.id in args)
            if any(count > 1 for count in uses.values()):
                raise _Unsupported
            for row in rows:
                assertion = _Substitute(row).visit(copy.deepcopy(template))
                result.append(_comparison(assertion, body[0], function.name, offsets, imports, after=True))
            table_seen = True
        if len(result) > MAX_CASES:
            raise _Unsupported
    if after and not table_seen:
        raise _Unsupported
    return imports, result


def mark_table_normalization(ir, raw_by_path, root_reader, root_searcher):
    """Attach only additive records; never alter an assertion or unit."""
    changed = [path for path, (before, after) in raw_by_path.items() if before != after]
    if len(changed) != 1:
        return
    for file in ir.files:
        if file.path != changed[0] or file.role != "test" or not file.parse_ok or file.status != "modified":
            continue
        before, after = raw_by_path[file.path]
        if not before or not after or b"parametrize" not in after:
            continue
        try:
            old_imports, old = _module(before, after=False)
            new_imports, new = _module(after, after=True)
            if old_imports != new_imports:
                continue
        except (_Unsupported, SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
            continue
        if (not inert_test_execution_context(file.path, root_reader, root_searcher)
                or not _pytest_unshadowed(file.path, root_reader)):
            continue
        records = []
        unchanged = Counter((case.operator, ast.dump(case.expected), ast.dump(case.subject)) for case in new)
        for previous in old:
            key = (previous.operator, ast.dump(previous.expected), ast.dump(previous.subject))
            if unchanged[key]:
                unchanged[key] -= 1
                continue
            for current in new:
                if (previous.operator != current.operator
                        or ast.dump(previous.expected) != ast.dump(current.expected)):
                    continue
                before_subject, after_subject = ast.unparse(previous.subject), ast.unparse(current.subject)
                if (expr_wraps(before_subject, after_subject)
                        or argument_wraps(before_subject, after_subject)):
                    records.append((current.unit, previous.text, previous.span, current.text, current.span,
                                    before_subject, after_subject, previous.operator, ast.unparse(previous.expected)))
        file.table_normalization_events = tuple(dict.fromkeys(records))
