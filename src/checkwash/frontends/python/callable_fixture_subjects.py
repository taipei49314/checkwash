"""Closed fixture factories substituting an asserted production callback.

Only additive installation evidence is returned. The ordinary assertions,
alignment and strength remain unchanged, and opaque callbacks stay unknown.
"""
from __future__ import annotations

import ast
import copy

from checkwash.frontends.python.callable_fixture_expectations import _factory_result, _module, _number, _parameters
from checkwash.frontends.python.expected_constants import folded_expected
from checkwash.frontends.python.frontend import _Offsets, normalize_source
from checkwash.frontends.python.oracle_purity import pure_imported_calls
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import stable_dump
from checkwash.pyenv import known_baseline


def _replacement(before, after):
    from .table_oracles import _Substitute
    old, new = _module(before, False), _module(after, True, fixture_factory=True)
    if old is None or new is None or old[0] != new[0] or old[1].name != new[1].name:
        return None
    if len(old[1].body) != 1 or len(new[1].body) not in (1, 2):
        return None
    previous, current = old[1].body[0], new[1].body[-1]
    if any(not isinstance(node, ast.Assert) or node.msg is not None
           or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1
           or not isinstance(node.test.ops[0], ast.Eq) for node in (previous, current)):
        return None
    original = previous.test.left
    if (not isinstance(original, ast.Call) or original.keywords or not all(_number(arg) for arg in original.args)
            or not isinstance(original.func, ast.Call) or original.func.keywords
            or not isinstance(original.func.func, ast.Name) or original.func.func.id not in old[0]
            or not all(_number(arg) for arg in original.func.args) or not _number(previous.test.comparators[0])
            or stable_dump(previous.test.comparators[0]) != stable_dump(current.test.comparators[0])):
        return None
    local = {}
    if len(new[1].body) == 2:
        assignment = new[1].body[0]
        if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Name)
                or assignment.targets[0].id in set(new[0]) | {new[1].name, new[2].name, 'pytest'}
                or not isinstance(assignment.value, ast.Call)):
            return None
        local[assignment.targets[0].id] = assignment.value
    actual = _Substitute(local).visit(copy.deepcopy(current.test.left))
    if (not isinstance(actual, ast.Call) or actual.keywords or not isinstance(actual.func, ast.Call)
            or actual.func.keywords or not isinstance(actual.func.func, ast.Name) or actual.func.func.id != new[2].name
            or [stable_dump(arg) for arg in actual.args] != [stable_dump(arg) for arg in original.args]
            or [stable_dump(arg) for arg in actual.func.args] != [stable_dump(arg) for arg in original.func.args]):
        return None
    # An otherwise-unused assignment can fail before the assertion. If a
    # capture is present, it must be the factory call actually consumed.
    if local and not (isinstance(current.test.left.func, ast.Name)
                      and current.test.left.func.id in local):
        return None
    factory = new[2].body[0]
    outer = _parameters(factory)
    callback = factory.body[0].value
    inner = _parameters(callback)
    if len(outer) != len(actual.func.args) or len(inner) != len(actual.args):
        return None
    # The nested callback's own parameters shadow captured factory names.
    bindings = dict(zip(outer, actual.func.args))
    bindings.update(zip(inner, actual.args))
    value = folded_expected(_Substitute(bindings).visit(copy.deepcopy(callback.body)), lambda _: False)
    if value is None or not _number(value):
        return None  # a raising callback never reaches the comparison
    return old, new, original, current


def callable_fixture_subject_events(ir, changes, *, root_reader=None, root_searcher=None):
    from .table_oracles import _context_snapshots, _pytest_unshadowed
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (not change.before or not change.after or b'fixture' not in change.after or b'lambda' not in change.after
            or change.status != 'modified' or change.old_path is not None):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        parsed = _replacement(change.before, change.after)
        if parsed is None:
            return []
        old, new, original, current = parsed
        target = '.'.join(old[0][original.func.func.id])
        if target.split('.', 1)[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        unit = next((unit for unit in file.units if unit.qualname == old[1].name), None)
        if unit is None or unit.before is None or unit.after is None or unit.delta is None:
            return []
        snapshots = _context_snapshots(change.path, change.before, change.after, changes, root_reader, root_searcher)
        for source, (read, search) in zip((change.before, change.after), snapshots):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not pure_imported_calls(source, [original.func], path=change.path, read=read,
                        result_proof=lambda data, name, call: _factory_result(data, name, call, len(original.args)))):
                return []
        offsets = _Offsets(normalize_source(change.after))
        return [(change.path, old[1].name, target, offsets.seg(current), offsets.span(current))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []
