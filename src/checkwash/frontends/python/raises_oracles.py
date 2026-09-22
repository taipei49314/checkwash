"""Retain closed exception oracles beside concrete table assertions.

Only a built-in ValueError check around one imported call on literal inputs
is split from its carrier. Its complete with statement and optional exact
message assertion survive projection. Callers require pure production and
unshadowed pytest on both snapshots, and retain every old exception block.
"""
import ast
import copy
import hashlib
from collections import Counter
from dataclasses import dataclass, replace

from checkwash.frontends.python.frontend import _Offsets, parse_python
from checkwash.ir.astutil import dotted_name, stable_dump


@dataclass
class RaisesOracle:
    owner: ast.FunctionDef
    body: list[ast.stmt]
    call: ast.Call

    @property
    def key(self):
        return stable_dump(ast.Module(body=self.body, type_ignores=[]))


def _literal(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in {type(None), bool, int, float, str, bytes}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return isinstance(node.operand, ast.Constant) and type(node.operand.value) in {int, float}
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_literal(item) for item in node.elts)
    return False


def extract_raises_oracles(tree):
    """Return retained blocks; unsupported statements remain for normal parsing."""
    nodes = list(ast.walk(tree))
    bindings = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bindings.update(node.arg for node in nodes if isinstance(node, ast.arg))
    bindings.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)))
    bindings.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    if (bindings['pytest'] != 1 or bindings['ValueError'] or bindings['str']
            or not any(isinstance(node, ast.Import) and len(node.names) == 1
                       and node.names[0].name == 'pytest' and node.names[0].asname is None for node in tree.body)):
        return []
    imports = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
               and node.module and not node.level for alias in node.names if alias.name != '*'}
    result, replacements = [], {}
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('test'):
            continue
        body, retained, index = function.body, [], 0
        while index < len(body):
            statement = body[index]
            if not (isinstance(statement, ast.With) and len(statement.items) == 1
                    and len(statement.body) == 1 and isinstance(statement.body[0], ast.Expr)
                    and isinstance(statement.body[0].value, ast.Call)):
                retained.append(statement)
                index += 1
                continue
            item, call = statement.items[0], statement.body[0].value
            context = item.context_expr
            if (not isinstance(context, ast.Call) or dotted_name(context.func) != 'pytest.raises'
                    or len(context.args) != 1 or dotted_name(context.args[0]) != 'ValueError'
                    or any(k.arg != 'match' or not isinstance(k.value, ast.Constant)
                           or type(k.value.value) is not str for k in context.keywords)
                    or len(context.keywords) > 1
                    or not isinstance(call.func, ast.Name) or call.func.id not in imports
                    or bindings[call.func.id] != 1 or not all(_literal(arg) for arg in call.args)
                    or not all(k.arg is not None and _literal(k.value) for k in call.keywords)):
                retained.append(statement)
                index += 1
                continue
            block = [statement]
            if item.optional_vars is not None:
                if (not isinstance(item.optional_vars, ast.Name) or index + 1 >= len(body)
                        or bindings[item.optional_vars.id] != 1):
                    retained.append(statement)
                    index += 1
                    continue
                name, message = item.optional_vars.id, body[index + 1]
                expected_left = ast.parse(f'str({name}.value)', mode='eval').body
                if (not isinstance(message, ast.Assert) or message.msg is not None
                        or not isinstance(message.test, ast.Compare) or len(message.test.ops) != 1
                        or not isinstance(message.test.ops[0], ast.Eq)
                        or stable_dump(message.test.left) != stable_dump(expected_left)
                        or not isinstance(message.test.comparators[0], ast.Constant)
                        or type(message.test.comparators[0].value) is not str
                        or sum(isinstance(node, ast.Name) and node.id == name for node in nodes) != 2):
                    retained.append(statement)
                    index += 1
                    continue
                block.append(message)
            result.append(RaisesOracle(copy.deepcopy(function), copy.deepcopy(block), copy.deepcopy(call)))
            index += len(block)
        if not retained and (function.decorator_list or function.args.args or function.args.posonlyargs
                             or function.args.kwonlyargs or function.args.vararg or function.args.kwarg
                             or function.returns or getattr(function, 'type_params', ())):
            return []  # do not erase fixture/decorator execution in exception-only tests
        replacements[function] = retained
    for function, body in replacements.items():
        function.body = body
    tree.body = [node for node in tree.body if node not in replacements or node.body]
    return result


def retain_raises_units(parsed, text, oracles):
    if not oracles:
        return parsed
    counts, definitions = Counter(), []
    for oracle in oracles:
        digest = hashlib.sha256(oracle.key.encode()).hexdigest()[:24]
        counts[digest] += 1
        name = f'test_exception_{digest}_{counts[digest]}'
        rendered = '\n'.join(ast.unparse(statement) for statement in oracle.body)
        definitions.append(f'def {name}():\n' + '\n'.join('    ' + line for line in rendered.splitlines()))
    projected = parse_python('\n'.join(definitions).encode(), collect_tests=True)
    offsets, units = _Offsets(text), list(parsed.units)
    for unit, oracle in zip(projected.units, oracles):
        span = offsets.span(oracle.owner)
        # The first assertion is the raises context; a second is its message.
        assertions = [replace(assertion, span=offsets.span(source))
                      for assertion, source in zip(unit.side.assertions, oracle.body)]
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=assertions)))
    return replace(parsed, units=units)
