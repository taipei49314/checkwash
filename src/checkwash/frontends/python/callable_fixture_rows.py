"""Literal string rows for assertion-bearing callable fixtures."""
import ast
import copy

from checkwash.ir.astutil import dotted_name


def fixture_prefix_rows(function, parameters):
    """Resolve exact request.param indexes, preserving every row and prefix."""
    if len(function.decorator_list) != 1:
        return None
    decorator = function.decorator_list[0]
    rows = None
    if isinstance(decorator, ast.Call):
        if decorator.args:
            return None
        if decorator.keywords:
            if (parameters != ['request'] or len(decorator.keywords) != 1
                    or decorator.keywords[0].arg != 'params'):
                return None
            rows = decorator.keywords[0].value
            if (not isinstance(rows, (ast.List, ast.Tuple)) or not 1 <= len(rows.elts) <= 64
                    or not all(isinstance(row, ast.Tuple) and row.elts
                               and all(isinstance(value, ast.Constant) and type(value.value) is str for value in row.elts)
                               for row in rows.elts)):
                return None
        decorator = decorator.func
    if dotted_name(decorator) != 'pytest.fixture' or (rows is None and parameters != []):
        return None
    if rows is None:
        return [function.body[:-1]]
    for statement in function.body[:-1]:
        indexes = [node.slice.value for node in ast.walk(statement)
                   if isinstance(node, ast.Subscript) and dotted_name(node.value) == 'request.param'
                   and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int]
        if len(indexes) != len(set(indexes)):
            return None  # preserve the ordinary row projection's repeated-binding guard

    class Cells(ast.NodeTransformer):
        def __init__(self, row):
            self.row = row

        def visit_Subscript(self, node):
            if (dotted_name(node.value) == 'request.param' and isinstance(node.slice, ast.Constant)
                    and type(node.slice.value) is int and 0 <= node.slice.value < len(self.row.elts)):
                return ast.copy_location(copy.deepcopy(self.row.elts[node.slice.value]), node)
            return self.generic_visit(node)

    result = []
    for row in rows.elts:
        prefix = [Cells(row).visit(copy.deepcopy(statement)) for statement in function.body[:-1]]
        if any(isinstance(node, ast.Name) and node.id == 'request' for statement in prefix for node in ast.walk(statement)):
            return None
        result.append(prefix)
    return result


def consumer_rows(function, parameters, fixture):
    """A sole direct parametrize decorator covers exactly the non-fixture args."""
    if not function.decorator_list:
        return [{}] if parameters == [fixture] else None
    if len(function.decorator_list) != 1:
        return None
    decorator = function.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or len(decorator.args) != 2 or decorator.keywords):
        return None
    names, rows = decorator.args
    if isinstance(names, ast.Constant) and type(names.value) is str:
        names = [name.strip() for name in names.value.split(',')]
    elif isinstance(names, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Constant) and type(item.value) is str for item in names.elts):
        names = [item.value for item in names.elts]
    else:
        return None
    if (not names or len(names) != len(set(names)) or not all(name.isidentifier() for name in names)
            or fixture in names or set(names) != set(parameters) - {fixture}
            or not isinstance(rows, (ast.List, ast.Tuple)) or not 1 <= len(rows.elts) <= 64):
        return None
    result = []
    for row in rows.elts:
        values = row.elts if len(names) > 1 and isinstance(row, (ast.List, ast.Tuple)) else [row]
        if len(values) != len(names) or not all(isinstance(value, ast.Constant) and type(value.value) is str for value in values):
            return None
        result.append(dict(zip(names, values)))
    return result
