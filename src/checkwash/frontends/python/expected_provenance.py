"""Additive, bounded evidence for literal expectations outside assert lines.

This is source substitution, not execution or refactor credit. Ordinary
helper actuals, helper-local bindings and finite literal loops retain their
input-to-answer relationship. Unsupported control flow remains with the
ordinary frontend; no assertion, alignment or strength is replaced here.
"""

from __future__ import annotations

import ast
import copy
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from checkwash.change import FileChange
from checkwash.frontends.python.frontend import _Offsets, normalize_source
from checkwash.frontends.python.table_oracles import MAX_AST_NODES, MAX_CASES, MAX_SOURCE_BYTES, _literal
from checkwash.ir.astutil import dotted_name

MAX_READS = 48
MAX_DEPTH = 8
MAX_EVENTS = 128
MAX_STEPS = 2048
_CALL_STATEMENT = re.compile(rb"(?m)^[ \t]+(?!assert\b)[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\(")
_HELPER_DEF = re.compile(rb"(?m)^def[ \t]+(?!test)")


class _Unsupported(Exception):
    pass


def _doc(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _name(text):
    parts = text.split(".")
    node = ast.Name(id=parts[0], ctx=ast.Load())
    for part in parts[1:]:
        node = ast.Attribute(value=node, attr=part, ctx=ast.Load())
    return node


class _Replace(ast.NodeTransformer):
    def __init__(self, env):
        self.env = env

    def visit_Name(self, node):
        return copy.deepcopy(self.env.get(node.id, node))


def _assign(target, value, env):
    if isinstance(target, ast.Name):
        env[target.id] = value
    elif (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
          and len(target.elts) == len(value.elts)):
        for child, item in zip(target.elts, value.elts):
            _assign(child, item, env)
    else:
        raise _Unsupported


@dataclass
class _Module:
    path: str
    offsets: _Offsets
    env: dict
    functions: dict
    tests: list


def _module(path, source):
    if len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported
    text = normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise _Unsupported
    env, functions, tests = {}, {}, []
    for node in tree.body:
        if _doc(node) or isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parent = list(PurePosixPath(path).parent.parts)
                if node.level > len(parent):
                    raise _Unsupported
                base = parent[:len(parent) - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            for alias in node.names:
                if not module or alias.name == "*":
                    raise _Unsupported
                env[alias.asname or alias.name] = _name(module + "." + alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                env[alias.asname or alias.name.split(".")[0]] = _name(alias.name if alias.asname else alias.name.split(".")[0])
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node
            env.pop(node.name, None)
            if node.name.startswith("test"):
                tests.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            tests.extend((node.name + "." + fn.name, fn) for fn in node.body
                         if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            value = _Replace(env).visit(copy.deepcopy(node.value))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                _assign(target, value, env)
        else:
            raise _Unsupported
    return _Module(path, _Offsets(text), env, functions, tests)


class _Reader:
    def __init__(self, raw, reader, role_of, report_context=None, sources=None):
        self.raw, self.reader, self.role_of = raw, reader, role_of
        self.context = report_context
        self.sources, self.modules = dict(sources or {}), {}
        self.reads = 0

    def source(self, path, side):
        if path in self.raw:
            return self.raw[path][side]
        if path not in self.sources:
            if self.reader is None or self.reads >= MAX_READS:
                raise _Unsupported
            self.reads += 1
            self.sources[path] = self.reader(path)
            if self.context is not None and self.sources[path] is not None:
                self.context.snapshot(path, 0, self.sources[path])
                self.context.snapshot(path, 1, self.sources[path])
        return self.sources[path]

    def module(self, path, side):
        key = (path, side)
        if key not in self.modules:
            source = self.source(path, side)
            self.modules[key] = _module(path, source) if source is not None else None
        return self.modules[key]

    def imported(self, origin, name, side):
        module, _, member = name.rpartition(".")
        if not module or any(not part.isidentifier() for part in name.split(".")):
            return None
        stem = module.replace(".", "/")
        candidates = {stem + ".py", stem + "/__init__.py"}
        if "." not in module and str(PurePosixPath(origin).parent) != ".":
            sibling = str(PurePosixPath(origin).parent / module)
            candidates.update({sibling + ".py", sibling + "/__init__.py"})
        present = [p for p in sorted(candidates) if self.source(p, side) is not None]
        if len(present) != 1 or self.role_of(present[0]) not in ("test", "conftest"):
            return None
        target = self.module(present[0], side)
        return (target, target.functions[member]) if target is not None and member in target.functions else None


@dataclass
class _Event:
    unit: str
    subject: str
    operator: str
    expected: str
    indirect: bool
    text: str
    span: tuple[int, int]


class _Project:
    def __init__(self, reader, side):
        self.reader, self.side = reader, side
        self.steps = 0

    def tick(self, depth):
        self.steps += 1
        if depth > MAX_DEPTH or self.steps > MAX_STEPS:
            raise _Unsupported

    def target(self, module, node, env):
        name = dotted_name(_Replace(env).visit(copy.deepcopy(node)))
        if name in module.functions:
            return module, module.functions[name]
        return self.reader.imported(module.path, name or "", self.side)

    def arguments(self, module, function, call, actuals):
        args = function.args
        if function.decorator_list or args.vararg or args.kwarg or getattr(function, "type_params", ()):
            raise _Unsupported
        params = [a.arg for a in [*args.posonlyargs, *args.args]]
        kwonly = [a.arg for a in args.kwonlyargs]
        if len(call.args) > len(params) or any(isinstance(a, ast.Starred) for a in call.args):
            raise _Unsupported
        env = dict(module.env)
        bound = dict(zip(params, actuals[:len(call.args)]))
        for key, value in zip(call.keywords, actuals[len(call.args):]):
            if key.arg is None or key.arg in bound or key.arg not in params + kwonly or key.arg in [a.arg for a in args.posonlyargs]:
                raise _Unsupported
            bound[key.arg] = value
        defaults = dict(zip(params[len(params) - len(args.defaults):], args.defaults))
        defaults.update({name: value for name, value in zip(kwonly, args.kw_defaults) if value is not None})
        for name in params + kwonly:
            if name not in bound:
                if name not in defaults or not _literal(defaults[name]):
                    raise _Unsupported
                bound[name] = defaults[name]
        env.update(bound)
        return env

    def resolve(self, module, node, env, depth, *, returns=False):
        self.tick(depth)
        result = _Replace(env).visit(copy.deepcopy(node))
        if sum(1 for _ in ast.walk(result)) > MAX_AST_NODES:
            raise _Unsupported
        # A literal-return table helper may supply a loop's finite iterable.
        # No repository expression is evaluated, including calls in defaults.
        if returns and isinstance(result, ast.Call):
            try:
                target = self.target(module, result.func, {})
            except _Unsupported:
                target = None  # an opaque subject call is still source, not a helper
            if target is not None:
                helper, function = target
                body = [s for s in function.body if not _doc(s) and not isinstance(s, ast.Pass)]
                if body and isinstance(body[-1], ast.Return) and all(isinstance(s, (ast.Assign, ast.AnnAssign)) for s in body[:-1]):
                    actuals = [self.resolve(module, a, {}, depth + 1) for a in [*result.args, *(k.value for k in result.keywords)]]
                    local = self.arguments(helper, function, result, actuals)
                    for assignment in body[:-1]:
                        self.binding(helper, assignment, local, depth + 1)
                    return self.resolve(helper, body[-1].value or ast.Constant(value=None), local, depth + 1, returns=True)
        return result

    def binding(self, module, statement, env, depth):
        if statement.value is None:
            raise _Unsupported
        value = self.resolve(module, statement.value, env, depth)
        for target in (statement.targets if isinstance(statement, ast.Assign) else [statement.target]):
            _assign(target, value, env)

    def walk(self, module, body, env, unit, events, depth=0, anchor=None, loop=False):
        for statement in body:
            self.tick(depth)
            if _doc(statement) or isinstance(statement, ast.Pass):
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self.binding(module, statement, env, depth)
            elif isinstance(statement, ast.For) and not statement.orelse:
                rows = self.resolve(module, statement.iter, env, depth, returns=True)
                if not isinstance(rows, (ast.Tuple, ast.List)) or not 0 < len(rows.elts) <= MAX_CASES or not _literal(rows):
                    raise _Unsupported
                for row in rows.elts:
                    local = dict(env)
                    _assign(statement.target, row, local)
                    self.walk(module, statement.body, local, unit, events, depth + 1, anchor, True)
                    env.update(local)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                target = self.target(module, call.func, env)
                if target is None:
                    raise _Unsupported
                helper, function = target
                actuals = [self.resolve(module, a, env, depth + 1) for a in [*call.args, *(k.value for k in call.keywords)]]
                local = self.arguments(helper, function, call, actuals)
                at = anchor or (module.offsets.seg(statement), module.offsets.span(statement))
                self.walk(helper, function.body, local, unit, events, depth + 1, at, loop)
            elif isinstance(statement, ast.Assert) and statement.msg is None:
                comparison = statement.test
                if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], (ast.Eq, ast.Is)):
                    raise _Unsupported
                left = self.resolve(module, comparison.left, env, depth)
                right = self.resolve(module, comparison.comparators[0], env, depth)
                surface = comparison.comparators[0]
                if _literal(left) and not _literal(right):
                    left, right, surface = right, left, comparison.left
                # This channel needs a concrete subject call. Unknown fixtures,
                # overloaded shapes and direct expectation-call rewrites keep
                # their existing detector ownership.
                if not isinstance(left, ast.Call):
                    continue
                indirect = bool(anchor or loop or any(isinstance(n, ast.Name) and n.id in env for n in ast.walk(surface)))
                if not _literal(right) and anchor is None:
                    continue
                if any(isinstance(n, (ast.Lambda, ast.NamedExpr, ast.Await, ast.Yield, ast.comprehension)) for n in ast.walk(right)):
                    raise _Unsupported
                if isinstance(comparison.ops[0], ast.Is) and not (isinstance(right, ast.Constant) and type(right.value) in (bool, type(None))):
                    continue
                text, span = anchor or (module.offsets.seg(statement), module.offsets.span(statement))
                events.append(_Event(unit, ast.unparse(left), type(comparison.ops[0]).__name__, ast.unparse(right), indirect, text, span))
                if len(events) > MAX_EVENTS:
                    raise _Unsupported
            elif isinstance(statement, ast.Return) and anchor is not None:
                return
            else:
                raise _Unsupported

    def events(self, module):
        result = []
        for unit, function in module.tests:
            if function.decorator_list:
                continue
            events = []
            try:
                env = dict(module.env)
                for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
                    env[arg.arg] = ast.Name(id=arg.arg, ctx=ast.Load())
                self.walk(module, function.body, env, unit, events)
            except _Unsupported:
                continue
            result.extend(events)
            if len(result) > MAX_EVENTS:
                raise _Unsupported
        return result


def importer_changes(changes, config, reader, searcher, reviewed_root_modules=()):
    """Discover unchanged tests importing a changed test-side helper, bounded."""
    if reader is None or searcher is None:
        return []
    raw = {c.path.replace("\\", "/"): (c.before, c.after) for c in changes}
    needles = set()
    for path, (before, after) in raw.items():
        if (before is None or before == after or not path.endswith(".py")
                or config.role_of(path) not in ("test", "conftest")
                or ("/" not in path and path[:-3] in reviewed_root_modules)
                or _HELPER_DEF.search(before) is None):
            continue
        try:
            module = _module(path, before)
        except (SyntaxError, ValueError, RecursionError, MemoryError, _Unsupported):
            continue
        if any(not name.startswith("test") for name in module.functions):
            needles.add(PurePosixPath(path).stem)
    if not needles or len(needles) > 16:
        return []
    candidates = sorted({p.replace("\\", "/") for p in searcher(sorted(needles))})
    if len(candidates) >= 64:
        return []
    found = []
    reads = 0
    for path in candidates:
        if (path in raw or not path.endswith(".py") or config.role_of(path) != "test"
                or path.startswith("/") or ":" in path or any(p in ("", ".", "..") for p in path.split("/"))):
            continue
        if reads >= MAX_READS:
            return []
        reads += 1
        source = reader(path)
        if source is not None and len(source) <= MAX_SOURCE_BYTES:
            found.append(FileChange(path=path, status="modified", before=source, after=source, synthetic="expected_provenance_importer"))
    return found


def _eligible(file, sources):
    # Native literal edits already have detector ownership. Reuse the IR
    # instead of reparsing every ordinary assertion diff (including unchanged
    # files carried by batch adapters). Calls without inherited asserts still
    # need the module-attribute helper channel.
    if any(a.inherited or (a.form == "compare_eq" and a.right_value is None)
           for unit in file.units for side in (unit.before, unit.after) if side is not None
           for a in side.assertions):
        return True
    return any(_CALL_STATEMENT.search(data) for data in sources if data is not None)


def mark_expected_provenance(ir, raw, reader, role_of, report_context=None, sources=None):
    source = _Reader(raw, reader, role_of, report_context, sources)
    for file in ir.files:
        if file.language != "python" or file.role != "test" or not file.parse_ok or file.path not in raw:
            continue
        if any(side is None for side in raw[file.path]):
            continue
        if not _eligible(file, raw[file.path]):
            continue
        try:
            before = _Project(source, 0).events(source.module(file.path, 0))
            after = _Project(source, 1).events(source.module(file.path, 1))
        except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, _Unsupported):
            continue
        old, new = defaultdict(list), defaultdict(list)
        for event, groups in [(e, old) for e in before] + [(e, new) for e in after]:
            groups[(event.unit, event.subject, event.operator)].append(event)
        records = []
        for key in sorted(old.keys() & new.keys()):
            wanted, got = Counter(e.expected for e in old[key]), Counter(e.expected for e in new[key])
            # Per input, preserve the established additions/reorders/dedup
            # controls. Comparing a global bag would swap answers for free.
            if wanted <= got or got <= wanted:
                continue
            lost = next(e for e in old[key] if e.expected in wanted - got)
            arrived = next(e for e in new[key] if e.expected in got - wanted)
            if not (lost.indirect or arrived.indirect):
                continue
            records.append((key[0], lost.text, lost.span, arrived.text, arrived.span,
                            key[1], key[2], lost.expected, arrived.expected))
        file.expected_provenance_events = tuple(records)
