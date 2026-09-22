"""Inert literal return metadata on an otherwise plain collected function."""
import ast
import copy

from .oracle_blocks import _args


def strip_none_test_returns(tree):
    """The caller must separately exclude observers of this changed metadata."""
    changed = set()
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or not isinstance(function.returns, ast.Constant) or function.returns.value is not None):
            continue
        plain = copy.copy(function)
        plain.returns = None
        if _args(plain) == []:
            function.returns = None
            changed.add(function.name)
    return changed
