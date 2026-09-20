"""Expected output owned by an explicitly checked same-module doctest runner."""
from __future__ import annotations

import ast
import copy
import doctest

from checkwash.ir import strength as S
from checkwash.ir.model import Assertion


def module_examples(tree: ast.Module, offsets) -> list[Assertion]:
    """Read examples, never execute them or infer pytest's doctest options."""
    if not any(isinstance(node, ast.Import) and any(alias.name == "doctest" and not alias.asname
                                                  for alias in node.names) for node in tree.body):
        return []
    if not any(isinstance(node, ast.Import) and any(alias.name == "sys" and not alias.asname
                                                  for alias in node.names) for node in tree.body):
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"doctest", "sys", "__name__"} and isinstance(node.ctx, (ast.Store, ast.Del)):
            return []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in {"doctest", "sys"}:
            return []
        if isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in {"doctest", "sys"}:
            if node.name not in {"doctest", "sys"} or node.asname:
                return []
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if isinstance(node.value, ast.Name) and node.value.id in {"doctest", "sys"}:
                return []
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
            "setattr", "delattr", "exec", "eval", "globals", "locals", "vars",
        }:
            return []
    result = []
    parser = doctest.DocTestParser()

    def visit(scope, prefix):
        body = scope.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            document = body[0].value
            try:
                examples = parser.get_examples(document.value)
            except ValueError:
                examples = []
            for number, example in enumerate(examples):
                if not example.want or example.options or example.exc_msg is not None:
                    continue
                source = example.source.rstrip("\n")
                try:
                    parsed = ast.parse(source)
                except SyntaxError:
                    continue
                names = tuple(sorted({node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)}))
                result.append(Assertion(
                    id=f"d{len(result)}", form="compare_eq", strength=S.EXACT_VALUE,
                    text=f">>> {source}\n{example.want.rstrip()}", span=offsets.span(document),
                    left=f"__doctest_output__({prefix!r}, {source!r})",
                    right_literal=repr(example.want), right_value=repr(example.want),
                    left_names=names, inherited=True,
                ))
        # testmod finds module/class members, not unconstructed nested defs.
        if isinstance(scope, (ast.Module, ast.ClassDef)):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.decorator_list:
                    visit(node, f"{prefix}.{node.name}" if prefix else node.name)
    visit(tree, "")
    return result


def checked_examples(func, examples, dead):
    """Only `failures, _ = doctest.testmod(...); assert failures == 0`."""
    if not examples:
        return []
    if any(argument.arg in {"doctest", "sys", "__name__"} for argument in
           func.args.posonlyargs + func.args.args + func.args.kwonlyargs):
        return []
    for statement in func.body:
        if id(statement) in dead or not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        call = statement.value
        if (not isinstance(call, ast.Call) or call.keywords
                or not isinstance(call.func, ast.Attribute) or call.func.attr != "testmod"
                or not isinstance(call.func.value, ast.Name) or call.func.value.id != "doctest"):
            continue
        if not (len(call.args) == 1 and ast.unparse(call.args[0]) == "sys.modules[__name__]"):
            continue
        target = statement.targets[0]
        if not isinstance(target, (ast.Tuple, ast.List)) or len(target.elts) != 2 or not isinstance(target.elts[0], ast.Name):
            continue
        name = target.elts[0].id
        # A second write can hide the actual runner result from the assert.
        if sum(isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
               for node in ast.walk(func)) != 1:
            continue
        for check in func.body:
            if id(check) in dead or not isinstance(check, ast.Assert) or check.lineno <= statement.lineno:
                continue
            test = check.test
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == name
                    and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
                    and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == 0):
                return copy.deepcopy(examples)
    return []
