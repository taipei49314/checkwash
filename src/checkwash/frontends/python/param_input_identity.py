"""Two-sided input-role evidence for unchanged parametrized assertions.

This preserves a copy invariant, not concrete input coverage or arbitrary
f(input) equivalence. Only replacement rows differing in one active input
leaf and its copied answer can pair. Other removals keep their ordinary owner.
The separate shared-producer proof follows the same unchanged local function
object through its evaluated decorators, never an unused nested definition.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from checkwash.change import EngineError
from checkwash.frontends.python.frontend import _Offsets, normalize_source
from checkwash.ir.model import param_tables

_MAX_BYTES = 250_000
_MAX_NODES = 40_000
_MAX_ROWS = 128
_TYPES = {"str", "int", "float", "bool"}


class _Unproved(Exception):
    pass


def _key(node):
    return ast.unparse(node)


def _doc(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _tree(source):
    if source is None or len(source) > _MAX_BYTES:
        raise _Unproved
    text = normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise _Unproved
    return tree, _Offsets(text)


def _bindings(tree):
    """All lexical binds, including parameters that could shadow authorities."""
    result = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            result[node.id] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result[node.name] += 1
        elif isinstance(node, ast.arg):
            result[node.arg] += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                result[alias.asname or alias.name.split('.')[0]] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            result[node.name] += 1
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            result[node.name] += 1
    return result


def _body(function):
    return tuple(_key(node) for node in function.body if not _doc(node))


def _inert_literal(node):
    if any(isinstance(child, (ast.Call, ast.Name, ast.Attribute, ast.Subscript)) for child in ast.walk(node)):
        return False
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError):
        return False


def _direct_params(function):
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or _key(decorator.func) != 'pytest.mark.parametrize':
            return False
        for keyword in decorator.keywords:
            if keyword.arg is None or keyword.arg == 'indirect' and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            ):
                return False
    return bool(function.decorator_list)


def _providers_unchanged(before, after, function):
    """A source-identical local decorator cannot borrow a changed provider."""
    local = _bindings(function)
    roots = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            callee = node.func
            while isinstance(callee, ast.Attribute):
                callee = callee.value
            if not isinstance(callee, ast.Name):
                return False
            if not local[callee.id]:
                roots.add(callee.id)
    environments = []
    for tree in (before, after):
        binds = _bindings(tree)
        env = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                env[node.name] = node
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    env[alias.asname or alias.name.split('.')[0]] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = node
        dependencies, pending = set(), list(roots)
        while pending:
            name = pending.pop()
            if name in dependencies:
                continue
            dependencies.add(name)
            if len(dependencies) > 64:
                return False
            if binds[name] > 1 or binds[name] and name not in env:
                return False
            definition = env.get(name)
            if definition is not None and not isinstance(definition, (ast.Import, ast.ImportFrom)):
                bound = _bindings(definition)
                pending.extend(child.id for child in ast.walk(definition)
                               if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                               and not bound[child.id])
        aliases = set(dependencies)
        while True:
            added = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    value = node.value
                    while isinstance(value, (ast.Attribute, ast.Subscript)):
                        value = value.value
                    if isinstance(value, ast.Name) and value.id in aliases:
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        added.update(target.id for target in targets if isinstance(target, ast.Name))
            if added <= aliases:
                break
            aliases.update(added)
            if len(aliases) > 64:
                return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _key(node.func).split('.')[-1] in {
                'setattr', 'delattr', '__setattr__', '__delattr__', 'exec', 'eval', 'globals', 'locals', 'vars', '__import__'
            }:
                return False
            if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
                base = node
                while isinstance(base, (ast.Attribute, ast.Subscript)):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in aliases:
                    return False
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and '__dict__' in _key(node.func.value):
                return False
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = node.func.value
                while isinstance(receiver, (ast.Attribute, ast.Subscript)):
                    receiver = receiver.value
                if isinstance(receiver, ast.Name) and receiver.id in aliases - dependencies:
                    return False
        environments.append({name: _key(env[name]) if name in env else None for name in dependencies})
    return environments[0] == environments[1]


def _inputs(function, assertion, parameter_names):
    """Syntactic producer dependencies along a definite straight-line setup.

    As with an ordinary constructor argument, this records input consumption;
    it does not claim that an arbitrary callee mathematically depends on all
    arguments. Nested function bodies and unused decorator expressions are
    not traversed. Every followed local has one binding before the assertion.
    """
    binds = _bindings(function)
    params = set(parameter_names)
    if (any(binds[name] != 1 for name in params)
            or any(isinstance(node, (ast.Global, ast.Nonlocal, ast.NamedExpr))
                   or isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del))
                   for node in ast.walk(function))):
        raise _Unproved
    assignments, functions = {}, {}
    for node in function.body:
        if node.lineno >= assertion.lineno:
            break
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assignments[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assignments[node.target.id] = node.value
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node
    active, decorated, reached = set(), set(), set()

    def input_selection(node, seen=frozenset()):
        if isinstance(node, ast.Name):
            if node.id in params:
                return node.id, ()
            if node.id in assignments:
                if node.id in seen or binds[node.id] != 1:
                    raise _Unproved
                return input_selection(assignments[node.id], seen | {node.id})
        elif isinstance(node, (ast.Subscript, ast.Attribute)):
            base = input_selection(node.value, seen)
            if base is not None:
                name, path = base
                if isinstance(node, ast.Attribute):
                    return name, (*path, ('attribute', node.attr))
                if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
                    raise _Unproved
                return name, (*path, ('key', node.slice.value))
        return None

    def visit(node, via_decorator=False, seen=frozenset()):
        selected = input_selection(node)
        if selected is not None:
            active.add(selected)
            if via_decorator and not selected[1]:
                decorated.add(selected[0])
            return
        if isinstance(node, ast.Name):
            name = node.id
            if name in seen:
                raise _Unproved
            if name in assignments or name in functions:
                if binds[name] != 1:
                    raise _Unproved
                following = seen | {name}
                reached.add(name)
                if name in assignments:
                    visit(assignments[name], via_decorator, following)
                else:
                    function_object = functions[name]
                    # Defaults/annotations can execute separately and are
                    # deliberately outside this evaluated-decorator channel.
                    args = function_object.args
                    if (not function_object.decorator_list or args.defaults
                            or any(args.kw_defaults) or function_object.returns
                            or any(arg.annotation for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs])
                            or getattr(function_object, 'type_params', ())):
                        raise _Unproved
                    for decorator in function_object.decorator_list:
                        if not isinstance(decorator, ast.Call):
                            raise _Unproved
                        visit(decorator, True, following)
                    # A local callback that reaches back into its setup
                    # parameters could mutate them when the subject runs.
                    if any(isinstance(child, ast.Name) and child.id in params
                           for statement in function_object.body for child in ast.walk(statement)):
                        raise _Unproved
            return
        if isinstance(node, ast.Call):
            # A method receiver may itself be a produced object. A bare
            # callee name is not an input merely because its body mentions it.
            if isinstance(node.func, ast.Attribute):
                visit(node.func.value, via_decorator, seen)
            for value in [*node.args, *(keyword.value for keyword in node.keywords)]:
                visit(value, via_decorator, seen)
        elif isinstance(node, ast.Subscript):
            # A known container selection has a single selected producer;
            # a callback stored in a different slot is an unused decoy.
            container = node.value
            followed = set()
            while isinstance(container, ast.Name) and container.id in assignments:
                if container.id in followed or binds[container.id] != 1:
                    raise _Unproved
                followed.add(container.id)
                reached.add(container.id)
                container = assignments[container.id]
            if isinstance(container, (ast.Dict, ast.Tuple, ast.List)):
                if not isinstance(node.slice, ast.Constant):
                    raise _Unproved
                selection = node.slice.value
                if isinstance(container, ast.Dict):
                    keys = [key.value for key in container.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
                    if len(keys) != len(container.keys) or len(keys) != len(set(keys)) or selection not in keys:
                        raise _Unproved
                    visit(container.values[keys.index(selection)], via_decorator, seen)
                elif type(selection) is int and -len(container.elts) <= selection < len(container.elts):
                    visit(container.elts[selection], via_decorator, seen)
                else:
                    raise _Unproved
            else:
                visit(node.value, via_decorator, seen)
        elif isinstance(node, ast.Attribute):
            visit(node.value, via_decorator, seen)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for item in node.elts:
                visit(item, via_decorator, seen)
        elif isinstance(node, ast.Dict):
            for item in [*node.keys, *node.values]:
                if item is not None:
                    visit(item, via_decorator, seen)
        elif not isinstance(node, ast.Constant):
            raise _Unproved

    visit(assertion.test.left)

    # Only the statements on the active setup path may execute before the
    # oracle. An unused call/assignment may mutate an input or the produced
    # function object even without assigning its name again.
    def prefix(statements):
        for statement in statements:
            if statement is assertion:
                return
            if statement.lineno >= assertion.lineno:
                return
            if _doc(statement):
                continue
            if isinstance(statement, ast.FunctionDef) and statement.name in reached:
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if (len(targets) == 1 and isinstance(targets[0], ast.Name)
                        and (targets[0].id in reached or _inert_literal(statement.value))):
                    continue
            if isinstance(statement, ast.If) and any(child is assertion for child in ast.walk(statement)):
                branch = statement.body if any(child is assertion for node in statement.body for child in ast.walk(node)) else statement.orelse
                if any(isinstance(child, ast.Call) and not (isinstance(child.func, ast.Name) and child.func.id == 'isinstance')
                       for child in ast.walk(statement.test)):
                    raise _Unproved
                prefix(branch)
                return
            raise _Unproved

    prefix(function.body)
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            leaf = _key(node.func).split('.')[-1]
            if leaf in {'setattr', 'delattr', '__setattr__', '__delattr__', 'exec', 'eval', 'globals', 'locals', 'vars', '__import__'}:
                raise _Unproved
            if isinstance(node.func, ast.Attribute) and input_selection(node.func.value) is not None:
                raise _Unproved  # input/alias method calls can mutate the selected leaf
    return active, decorated


def _enum_classes(before, after, path, read):
    """Unchanged, plain standard Enum members; never arbitrary obj.property."""
    b_classes = {node.name: node for node in before.body if isinstance(node, ast.ClassDef)}
    b_binds, a_binds = _bindings(before), _bindings(after)
    enums = {}
    imports = [node for node in after.body if isinstance(node, ast.Import)
               and any(alias.name == 'enum' and alias.asname is None for alias in node.names)]
    b_imports = [node for node in before.body if isinstance(node, ast.Import)
                 and any(alias.name == 'enum' and alias.asname is None for alias in node.names)]
    if len(imports) != 1 or len(b_imports) != 1 or a_binds['enum'] != 1 or b_binds['enum'] != 1:
        return enums
    for node in after.body:
        if not isinstance(node, ast.ClassDef) or node.name not in b_classes:
            continue
        old = b_classes[node.name]
        if (_key(old) != _key(node) or node.decorator_list or node.keywords
                or len(node.bases) != 1 or _key(node.bases[0]) != 'enum.Enum'
                or a_binds[node.name] != 1 or b_binds[node.name] != 1
                or node.lineno < imports[0].lineno or old.lineno < b_imports[0].lineno
                or getattr(node, 'type_params', ())):
            continue
        members = set()
        for statement in node.body:
            if _doc(statement):
                continue
            if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                    or not isinstance(statement.targets[0], ast.Name)):
                break
            name, value = statement.targets[0].id, statement.value
            if name.startswith('_') or name in members:
                break
            if not (isinstance(value, ast.Constant) and type(value.value) in (str, int, bool, type(None))
                    or isinstance(value, ast.Call) and _key(value.func) == 'enum.auto'
                    and not value.args and not value.keywords):
                break
            members.add(name)
        else:
            if members:
                enums[node.name] = members
    if not enums:
        return enums
    # Reject visible mutation, aliases and dynamic namespace edits involving
    # the member authorities. Unrelated enum.StrEnum compatibility aliases do
    # not replace enum.Enum/enum.auto or one of these declared classes.
    for tree in (before, after):
        protected_aliases = {'enum', 'enum.Enum', 'enum.auto', *enums}
        harmless_aliases = set()
        # Account for the standard pre-3.11 StrEnum compatibility alias. It
        # does not permit subsequent writes or method calls through StrEnum.
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and _key(node.targets[0]) == 'enum.StrEnum' and _key(node.value) == 'enum.Enum'):
                protected_aliases.add('enum.StrEnum')
                harmless_aliases.add(id(node.targets[0]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if _key(node.func).split('.')[-1] in {
                    'getattr', 'setattr', 'delattr', '__getattribute__', '__setattr__', '__delattr__',
                    'exec', 'eval', 'globals', 'locals', 'vars', '__import__'
                }:
                    return {}
                if isinstance(node.func, ast.Attribute):
                    receiver = _key(node.func.value)
                    if any(receiver == name or receiver.startswith(name + '.') or receiver.startswith(name + '[')
                           for name in protected_aliases) and _key(node.func) != 'enum.auto':
                        return {}
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                value = node.value
                if isinstance(value, (ast.Name, ast.Attribute, ast.Subscript)) and any(
                    _key(value) == name or _key(value).startswith(name + '.') or _key(value).startswith(name + '[')
                    for name in protected_aliases
                ) and not (
                    isinstance(node, ast.Assign) and len(node.targets) == 1 and id(node.targets[0]) in harmless_aliases
                ):
                    return {}
                if isinstance(value, ast.Call) and any(_key(arg) in protected_aliases for arg in value.args):
                    return {}
            if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
                target = _key(node)
                if id(node) not in harmless_aliases and any(
                    target == name or target.startswith(name + '.') or target.startswith(name + '[')
                    for name in protected_aliases
                ):
                    return {}
    parts = PurePosixPath(path).parts[:-1]
    roots = {'', 'src', *('/'.join(parts[:index]) for index in range(1, len(parts) + 1))}
    for root in sorted(roots):
        prefix = root + '/' if root else ''
        for suffix in ('enum.py', 'enum/__init__.py'):
            if read(prefix + suffix) is not None:
                return {}
    return enums


def _value(node, enums, binds):
    """Canonical inert values. Dict ordering is irrelevant only in this proof."""
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
        return ('literal', type(node.value).__name__, repr(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float):
        return ('number', _key(node))
    if isinstance(node, ast.Name) and (node.id in enums or node.id in _TYPES and binds[node.id] == 0):
        return ('name', node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr in enums.get(node.value.id, ()):
        return ('enum', node.value.id, node.attr)
    if isinstance(node, (ast.Tuple, ast.List)):
        return (type(node).__name__, tuple(_value(child, enums, binds) for child in node.elts))
    if isinstance(node, ast.Dict):
        keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        if len(keys) != len(node.keys) or len(set(keys)) != len(keys):
            raise _Unproved
        return ('dict', tuple(sorted((key, _value(value, enums, binds)) for key, value in zip(keys, node.values))))
    raise _Unproved


def _row_keys(row, names, column, active, enums, binds):
    values = tuple(_value(ast.parse(cell, mode='eval').body, enums, binds) for cell in row)
    expected = values[column]
    for index, name in enumerate(names):
        if index == column or not any(parameter == name for parameter, _path in active):
            continue
        # A whole primitive cell, or one field of a literal keyword mapping.
        # Nested/combined projections and computed expected expressions fail.
        selected = values[index]
        leaves = [((), selected)] if selected[0] in {'literal', 'number', 'enum'} and (name, ()) in active else []
        if selected[0] == 'dict':
            leaves = [((key,), value) for key, value in selected[1]
                      if value[0] in {'literal', 'number', 'enum'}
                      and ((name, ()) in active or (name, (('key', key),)) in active)]
        for path, value in leaves:
            if value != expected:
                continue
            skeleton = list(values)
            skeleton[column] = ('copied-answer',)
            if not path:
                skeleton[index] = ('active-input',)
            else:
                skeleton[index] = ('dict', tuple((key, ('active-input',) if key == path[0] else val) for key, val in selected[1]))
            yield (index, path, tuple(skeleton))


def _copy_pairs(before, after, column, active, enums, binds):
    # A still-written disabled row is not a replacement. Subtract complete
    # rows first so surviving copies cannot consume a replacement witness.
    old = Counter(row for row, disabled in zip(before.rows, before.disabled) if not disabled) - Counter(after.rows)
    new = Counter(row for row, disabled in zip(after.rows, after.disabled) if not disabled) - Counter(before.rows)
    groups = [defaultdict(list), defaultdict(list)]
    for side, rows in enumerate((old, new)):
        for row in rows:
            try:
                for key in _row_keys(row, before.names, column, active, enums, binds):
                    groups[side][key].append(row)
            except (_Unproved, SyntaxError, ValueError):
                continue
    pairs = []
    for key in sorted(groups[0].keys() & groups[1].keys(), key=repr):
        for left in groups[0][key]:
            for right in groups[1][key]:
                if left[column] == right[column]:
                    continue  # unchanged answers already have their control
                count = min(old[left], new[right])
                pairs.extend((left, right) for _ in range(count))
                old[left] -= count
                new[right] -= count
    return pairs


def mark_param_input_identity(ir, raw_by_path, root_reader):
    """Attach optional source proofs; absent or unsupported facts give no credit."""
    cache = {}

    def read(path):
        if path not in cache:
            if path in raw_by_path:
                before, after = raw_by_path[path]
                if before != after:
                    raise _Unproved
                cache[path] = after
            else:
                if root_reader is None or len(cache) >= 48:
                    raise _Unproved
                cache[path] = root_reader(path)
                if cache[path] is not None and not isinstance(cache[path], bytes):
                    raise EngineError('parameter input proof strict reader returned invalid source bytes')
        return cache[path]

    for file in ir.files:
        if file.language != 'python' or file.role != 'test' or file.path not in raw_by_path:
            continue
        if any(path != file.path and before != after for path, (before, after) in raw_by_path.items()):
            continue  # an imported provider may have changed outside this file
        candidates = [unit for unit in file.units if unit.before and unit.after and unit.delta
                      and param_tables(unit.before) and param_tables(unit.before) != param_tables(unit.after)]
        if not candidates:
            continue
        try:
            before, b_offsets = _tree(raw_by_path[file.path][0])
            after, a_offsets = _tree(raw_by_path[file.path][1])
            b_funcs = {node.name: node for node in before.body if isinstance(node, ast.FunctionDef)}
            a_funcs = {node.name: node for node in after.body if isinstance(node, ast.FunctionDef)}
            enums = _enum_classes(before, after, file.path, read)
        except (_Unproved, SyntaxError, UnicodeError, ValueError, RecursionError, MemoryError):
            continue
        binds = _bindings(after) | _bindings(before)
        shared, rewrites = [], []
        for unit in candidates:
            b_func, a_func = b_funcs.get(unit.qualname), a_funcs.get(unit.qualname)
            if (b_func is None or a_func is None or _body(b_func) != _body(a_func)
                    or _key(b_func.args) != _key(a_func.args) or not _direct_params(b_func) or not _direct_params(a_func)
                    or binds[unit.qualname] != 1 or not _providers_unchanged(before, after, a_func)):
                continue
            unit_enums = {
                name: members for name, members in enums.items()
                if all(next(node.lineno for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
                       < min(decorator.lineno for decorator in function.decorator_list)
                       for tree, function in ((before, b_func), (after, a_func)))
            }
            b_nodes = {b_offsets.span(node): node for node in ast.walk(b_func) if isinstance(node, ast.Assert)}
            a_nodes = {a_offsets.span(node): node for node in ast.walk(a_func) if isinstance(node, ast.Assert)}
            b_asserts = {assertion.id: assertion for assertion in unit.before.assertions}
            a_asserts = {assertion.id: assertion for assertion in unit.after.assertions}
            for pair in unit.delta.assertion_pairs:
                b, a = b_asserts[pair.before_id], a_asserts[pair.after_id]
                b_node, a_node = b_nodes.get(tuple(b.span)), a_nodes.get(tuple(a.span))
                if (b.inherited or a.inherited or b_node is None or a_node is None or _key(b_node) != _key(a_node)
                        or not isinstance(a_node.test, ast.Compare) or len(a_node.test.ops) != 1
                        or not isinstance(a_node.test.ops[0], ast.Eq)):
                    continue
                try:
                    b_active, b_decorated = _inputs(b_func, b_node, {name for table in param_tables(unit.before) for name in table.names})
                    a_active, a_decorated = _inputs(a_func, a_node, {name for table in param_tables(unit.after) for name in table.names})
                except _Unproved:
                    continue
                active = b_active & a_active
                consumed = set(b.right_depends_on) & set(a.right_depends_on)
                for name in sorted(consumed & b_decorated & a_decorated):
                    shared.append((unit.qualname, b.id, a.id, name))
                for old in param_tables(unit.before):
                    hits = [new for new in param_tables(unit.after) if new.names == old.names]
                    if len(hits) != 1 or len(old.rows) > _MAX_ROWS or len(hits[0].rows) > _MAX_ROWS:
                        continue
                    for name in sorted(consumed & set(old.names)):
                        if sum(name in table.names for table in param_tables(unit.before)) != 1:
                            continue
                        for left, right in _copy_pairs(old, hits[0], old.names.index(name), active, unit_enums, binds):
                            rewrites.append((unit.qualname, b.id, a.id, name, left, right))
        file.shared_param_input_pairs = tuple(shared)
        file.param_input_identity_pairs = tuple(rewrites)
