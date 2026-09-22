"""Closed immutable row sources inside a default TestCase class."""
import ast
import copy

from checkwash.frontends.python.table_factories import _immutable

_DATA_NAMES = {'data', 'cases', 'rows', 'test_cases', 'test_data', 'input_data'}


def expand_class_tables(node, tree):
    bound = {item.id for item in ast.walk(tree) if isinstance(item, ast.Name) and not isinstance(item.ctx, ast.Load)}
    bound.update(item.name for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)))
    bound.update(item.arg for item in ast.walk(tree) if isinstance(item, ast.arg))
    bound.update(item.asname or item.name.split('.')[0] for item in ast.walk(tree) if isinstance(item, ast.alias))
    for member in list(node.body):
        if (not isinstance(member, ast.FunctionDef) or len(member.decorator_list) != 1
                or not isinstance(member.decorator_list[0], ast.Name) or member.returns
                or getattr(member, 'type_params', ()) or len(member.body) != 1):
            continue
        decorator = member.decorator_list[0].id
        if decorator not in {'staticmethod', 'classmethod'} or decorator in bound:
            continue
        args = member.args
        if (args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
                or any(arg.annotation for arg in args.args)):
            continue
        statement, assigned = member.body[0], None
        if decorator == 'staticmethod' and not args.args and isinstance(statement, ast.Return):
            if member.name.startswith(('test', '__', 'pytest_')):
                continue
            name, value, call = member.name, statement.value, True
        elif (decorator == 'classmethod' and member.name == 'setUpClass' and len(args.args) == 1
              and args.args[0].arg == 'cls' and isinstance(statement, ast.Assign) and len(statement.targets) == 1
              and isinstance(statement.targets[0], ast.Attribute) and isinstance(statement.targets[0].value, ast.Name)
              and statement.targets[0].value.id == 'cls'):
            assigned = statement.targets[0]
            name, value, call = assigned.attr, statement.value, False
            if name.startswith('__'):
                continue
        else:
            continue
        if name not in _DATA_NAMES:
            continue  # never erase an implicit TestCase dispatcher or control attribute
        if not call and any(isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name for item in node.body):
            continue
        if (not isinstance(value, (ast.List, ast.Tuple)) or not 1 <= len(value.elts) <= 64
                or not all(_immutable(row) for row in value.elts)):
            continue
        if sum(isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == member.name for item in node.body) != 1:
            continue
        references = [item for item in ast.walk(node) if isinstance(item, ast.Attribute) and item.attr == name
                      and item is not assigned]
        replacements = []
        for test in node.body:
            if (not isinstance(test, ast.FunctionDef) or not test.name.startswith('test')
                    or len(test.body) != 1 or not isinstance(test.body[0], ast.For)):
                continue
            loop = test.body[0]
            target = loop.iter
            if call:
                if not isinstance(target, ast.Call) or target.args or target.keywords:
                    continue
                target = target.func
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == 'self' and target.attr == name and isinstance(target.ctx, ast.Load)):
                replacements.append((loop, target))
        if not replacements or {id(item) for item in references} != {id(target) for _, target in replacements}:
            continue
        for loop, _ in replacements:
            loop.iter = copy.deepcopy(value)
        node.body.remove(member)
