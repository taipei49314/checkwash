"""Boolean answers derived from a closed immutable fixture's membership.

The tuple's ordered rows instantiate one existing production call per item.
No assertion normalization or equivalence credit is granted: this only keeps
a replaced literal Boolean answer visible to ordinary provenance policy.
"""
from __future__ import annotations

import ast
import copy
from collections import Counter, defaultdict

from .callable_fixture_expectations import _parameters, _tree
from .frontend import _Offsets, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump

_CONTROL = IMPLICIT_ENTRY_NAMES | {'setUpModule', 'tearDownModule', 'pytest', 'pytestmark', 'pytest_plugins'}


def _integer(node):
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value.bit_length() <= 256


def _module(source, after):
    tree = _tree(source)
    if tree is None:
        return None
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if (after and isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None
              and not node.level and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported = node
            name = node.names[0].asname or node.names[0].name
            if name in _CONTROL:
                return None
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            functions.append(node)
            name = node.name
            if name in _CONTROL:
                return None
        else:
            return None
        if name in occupied or name.startswith(('__', 'pytest_')):
            return None
        occupied.add(name)
    if imported is None or len(functions) != (2 if after else 1) or after and not pytest:
        return None
    test = functions[-1]
    if not test.name.startswith('test') or test.decorator_list:
        return None
    provider = imported.names[0].asname or imported.names[0].name
    if not after:
        return (imported, test, provider) if _parameters(test) == [] else None
    fixture = functions[0]
    if (fixture.name.startswith('test') or _parameters(fixture) != []
            or _parameters(test) != [fixture.name] or len(fixture.decorator_list) != 1):
        return None
    decorator = fixture.decorator_list[0]
    if isinstance(decorator, ast.Call) and not decorator.args and not decorator.keywords:
        decorator = decorator.func
    if (dotted_name(decorator) != 'pytest.fixture' or len(fixture.body) != 1
            or not isinstance(fixture.body[0], ast.Return) or not isinstance(fixture.body[0].value, ast.Tuple)
            or not 0 < len(fixture.body[0].value.elts) <= 64
            or not all(_integer(item) for item in fixture.body[0].value.elts)):
        return None
    return imported, test, provider, fixture, fixture.body[0].value.elts


def _assertion(statement, provider):
    if (not isinstance(statement, ast.Assert) or statement.msg is not None
            or not isinstance(statement.test, ast.Compare) or len(statement.test.ops) != 1
            or not isinstance(statement.test.ops[0], (ast.Eq, ast.Is))):
        return None
    comparison = statement.test
    call = comparison.left
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
            or call.keywords or len(call.args) != 1):
        return None
    return call, comparison.comparators[0], type(comparison.ops[0]).__name__


def tuple_fixture_events(path, before, after, reader):
    from .table_oracles import _pytest_unshadowed
    if (not before or not after or b'fixture' not in after or b' in ' not in after
            or any(p != path and old != new for p, (old, new) in reader.raw.items())):
        return []
    try:
        old, new = _module(before, False), _module(after, True)
        if (old is None or new is None or old[1].name != new[1].name
                or stable_dump(old[0]) != stable_dump(new[0]) or not 0 < len(old[1].body) <= 64
                or len(new[1].body) != 1 or not isinstance(new[1].body[0], ast.For)):
            return []
        loop = new[1].body[0]
        if (loop.orelse or len(loop.body) != 1 or not isinstance(loop.target, ast.Name)
                or loop.target.id in {new[1].name, new[2], new[3].name, 'pytest'}
                or not isinstance(loop.iter, ast.Name) or loop.iter.id != new[3].name):
            return []
        check = _assertion(loop.body[0], new[2])
        if (check is None or not isinstance(check[0].args[0], ast.Name) or check[0].args[0].id != loop.target.id
                or not isinstance(check[1], ast.Compare) or len(check[1].ops) != 1
                or not isinstance(check[1].ops[0], (ast.In, ast.NotIn))
                or not isinstance(check[1].left, ast.Name) or check[1].left.id != loop.target.id
                or not isinstance(check[1].comparators[0], ast.Name) or check[1].comparators[0].id != new[3].name):
            return []
        previous, current = defaultdict(list), defaultdict(list)
        for statement in old[1].body:
            row = _assertion(statement, old[2])
            if (row is None or row[2] != check[2] or not _integer(row[0].args[0])
                    or not isinstance(row[1], ast.Constant) or type(row[1].value) is not bool):
                return []
            previous[stable_dump(row[0])].append((row[0], row[1].value, statement))
        for item in new[4]:
            call = copy.deepcopy(check[0])
            call.args = [item]
            # Each concrete item is drawn from this very tuple. Exact builtin
            # integers exclude custom membership/equality or mutable aliases.
            current[stable_dump(call)].append((call, isinstance(check[1].ops[0], ast.In), loop.body[0]))
        if any(len(rows) > len(current[key]) for key, rows in previous.items()):
            return []
        changes = []
        for key, rows in previous.items():
            wanted, got = Counter(row[1] for row in rows), Counter(row[1] for row in current[key])
            if not (wanted - got and got - wanted):
                continue
            lost = next(row for row in rows if row[1] in wanted - got)
            arrived = next(row for row in current[key] if row[1] in got - wanted)
            changes.append((lost, arrived))
        if not changes:
            return []
        for side, source, rows in ((0, before, previous), (1, after, current)):
            read = lambda candidate, side=side: reader.source(candidate, side, authority=True)
            search = lambda needles, side=side: reader.search(needles, side)
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, [row[0] for values in rows.values() for row in values],
                                               path=path, read=read, result_proof=primitive_literal_result)):
                return []
        offsets = [_Offsets(normalize_source(source)) for source in (before, after)]
        return [(old[1].name, offsets[0].seg(lost[2]), offsets[0].span(lost[2]),
                 offsets[1].seg(arrived[2]), offsets[1].span(arrived[2]), ast.unparse(lost[0]), check[2],
                 repr(lost[1]), repr(arrived[1])) for lost, arrived in changes]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []
