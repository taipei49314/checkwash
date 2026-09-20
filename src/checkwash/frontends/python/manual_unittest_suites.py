"""Expose the sole oracle in a closed, manually executed unittest suite.

Default loading, result construction, execution and success consumption must
all be present. No merely declared nested class or ignored result earns an
oracle. The original inner assertion supplies the reported text and span.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import replace

from .frontend import _Offsets, normalize_source, parse_python
from .neutralizing_aliases import _assertion
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _module_unshadowed, _pytest_unshadowed
from checkwash.ir.astutil import dotted_name

_RESERVED = IMPLICIT_ENTRY_NAMES | {'self', 'pytestmark', 'pytest_plugins'}


def _safe(name):
    return name not in _RESERVED and not name.startswith(('__', 'pytest_'))


def _call(node, name, arguments):
    return (isinstance(node, ast.Call) and dotted_name(node.func) == name and not node.keywords
            and len(node.args) == len(arguments)
            and all(isinstance(arg, ast.Name) and arg.id == expected for arg, expected in zip(node.args, arguments)))


def _assignment(node):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name))


def _module(source):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 3:
        return None
    standard, imported, test = None, None, body[-1]
    for node in body[:2]:
        if (isinstance(node, ast.Import) and len(node.names) == 1
                and node.names[0].name == 'unittest' and standard is None):
            standard = node
        elif (isinstance(node, ast.ImportFrom) and not node.level and node.module
              and len(node.names) == 1 and node.names[0].name != '*' and imported is None):
            imported = node
        else:
            return None
    if (standard is None or imported is None or not isinstance(test, ast.FunctionDef)
            or not test.name.startswith('test') or test.decorator_list or _args(test) != []
            or len(test.body) != 5):
        return None
    framework = standard.names[0].asname or standard.names[0].name
    provider = imported.names[0].asname or imported.names[0].name
    cls, loader, result, executed, success = test.body
    if (provider.startswith('test') or not isinstance(cls, ast.ClassDef) or cls.decorator_list
            or cls.keywords or getattr(cls, 'type_params', ()) or len(cls.bases) != 1
            or dotted_name(cls.bases[0]) != framework + '.TestCase' or len(cls.body) != 1
            or not _assignment(loader) or not _assignment(result)):
        return None
    method = cls.body[0]
    if (not isinstance(method, ast.FunctionDef) or not method.name.startswith('test')
            or not _safe(method.name) or method.decorator_list or _args(method) != ['self']
            or len(method.body) != 1 or not isinstance(method.body[0], ast.Expr)):
        return None
    suite_name, result_name = loader.targets[0].id, result.targets[0].id
    names = [framework, provider, test.name, cls.name, suite_name, result_name]
    if len(set(names)) != len(names) or not all(_safe(name) for name in names):
        return None
    if (not _call(loader.value, framework + '.defaultTestLoader.loadTestsFromTestCase', [cls.name])
            or not _call(result.value, framework + '.TestResult', [])
            or not isinstance(executed, ast.Expr) or not _call(executed.value, suite_name + '.run', [result_name])
            or not isinstance(success, ast.Assert) or success.msg is not None
            or not _call(success.test, result_name + '.wasSuccessful', [])):
        return None
    oracle = method.body[0].value
    if (not isinstance(oracle, ast.Call) or dotted_name(oracle.func) != 'self.assertEqual'
            or len(oracle.args) != 2 or oracle.keywords):
        return None
    comparison = ast.Assert(test=ast.Compare(left=copy.deepcopy(oracle.args[0]), ops=[ast.Eq()],
                                           comparators=[copy.deepcopy(oracle.args[1])]), msg=None)
    call = _assertion(comparison, provider)
    if call is None:
        return None
    try:
        ast.literal_eval(oracle.args[1])
    except (ValueError, TypeError):
        return None
    projected = copy.deepcopy(test)
    projected.body = [comparison]
    rendered = ast.unparse(ast.fix_missing_locations(ast.Module(body=[imported, projected], type_ignores=[])))
    parsed = parse_python(rendered.encode(), collect_tests=True)
    if not parsed.parse_ok or len(parsed.units) != 1 or len(parsed.units[0].side.assertions) != 1:
        return None
    return test, method.body[0], success, call, parsed.units[0].side.assertions[0]


def project_manual_unittest_suites(before, after, before_parsed, after_parsed, *, path,
                                   root_reader=None, root_searcher=None, changes=()):
    if root_reader is None or root_searcher is None or b'defaultTestLoader' not in before + after:
        return before_parsed, after_parsed
    originals = (before_parsed, after_parsed)
    projected = []
    try:
        for source, parsed, (read, search) in zip((before, after), originals, _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            module = _module(source) if parsed.parse_ok and b'defaultTestLoader' in source else None
            if module is None:
                projected.append(parsed)
                continue
            test, oracle, success, call, assertion = module
            offsets = _Offsets(normalize_source(source))
            if (len(parsed.units) != 1 or parsed.units[0].qualname != test.name
                    or len(parsed.units[0].side.assertions) != 1
                    or parsed.units[0].side.assertions[0].span != offsets.span(success)
                    or not inert_test_execution_context(path, read, search)
                    or not _pytest_unshadowed(path, read) or not _module_unshadowed(path, read, 'unittest')
                    or not pure_imported_calls(source, [call], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                projected.append(parsed)
                continue
            unit = parsed.units[0]
            # It executes in the nested method, not in the outer test's own
            # body. Preserve the existing inherited-oracle contract when a
            # later edit inlines the same check into the outer function.
            inner = replace(assertion, id='a0', text=offsets.seg(oracle), span=offsets.span(oracle), inherited=True)
            side = replace(unit.side, assertions=[inner], invoked=tuple(sorted({*unit.side.invoked, call.func.id})))
            projected.append(replace(parsed, units=[replace(unit, side=side)]))
        return tuple(projected)
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return originals
