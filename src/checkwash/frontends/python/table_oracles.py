"""Bounded, two-sided projection of an exact concrete test consolidation.

N native tests and one literal table can describe the same ordered N oracles.
Recognize only an entire module of imports and transparent test definitions:
one native comparison per case, one imported call with literal arguments, and
a literal expectation. No repository expression is executed. Subject/input
coverage must match before either side is projected. Expected values remain
on both sides for the ordinary detectors to compare; changing one cannot
acquire equivalence credit. Unsupported syntax keeps the ordinary frontend
output and detector findings.

The projected units represent concrete cases, not newly discovered functions.
Their stable identities and semantic assertions come from the concrete AST;
their spans still point into the actual source. This changes no alignment
threshold, assertion strength, detector severity, or exemption policy.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from checkwash.frontends.python.frontend import ParsedFile, _Offsets, normalize_source, parse_python
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name

MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 4_096
MAX_CASES = 64


@dataclass
class _Case:
    assertion: ast.Assert
    source_assertion: ast.Assert
    source_function: ast.FunctionDef


def _literal(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, float, str, bytes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and _literal(key) and _literal(value)
                   for key, value in zip(node.keys, node.values))
    return False


def _args(node):
    args = node.args
    if (not isinstance(node, ast.FunctionDef) or node.returns or getattr(node, "type_params", ())
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.vararg or args.kwarg
            or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Name) for item in node.elts):
        names = [item.id for item in node.elts]
        return names if len(names) == len(set(names)) else None
    return None


def _rows(table, names, *, unpack=True):
    if not isinstance(table, (ast.List, ast.Tuple)) or not 1 <= len(table.elts) <= MAX_CASES:
        return None
    result = []
    for row in table.elts:
        values = row.elts if unpack and isinstance(row, (ast.List, ast.Tuple)) else [row]
        if len(values) != len(names) or not all(_literal(value) for value in values):
            return None
        result.append(dict(zip(names, values)))
    return result


class _Substitute(ast.NodeTransformer):
    def __init__(self, bindings):
        self.bindings = bindings

    def visit_Name(self, node):
        return copy.deepcopy(self.bindings.get(node.id, node))


def _concrete(node, bindings, imports):
    if not isinstance(node, ast.Assert) or node.msg is not None:
        return None
    original = node.test
    if isinstance(original, ast.Compare):
        # Substitution copies a row's AST into each use. Reusing the same
        # object in two subject arguments, or as input and expectation, is
        # not equivalent to constructing two independent literal objects.
        # Decline every repeated row binding rather than guess mutability.
        uses = Counter(n.id for n in ast.walk(original) if isinstance(n, ast.Name) and n.id in bindings)
        if any(count > 1 for count in uses.values()):
            return None
    concrete = _Substitute(bindings).visit(copy.deepcopy(node))
    compare = concrete.test
    if not isinstance(compare, ast.Compare) or len(compare.ops) != 1:
        return None
    actual, expected = compare.left, compare.comparators[0]
    if not isinstance(compare.ops[0], (ast.Eq, ast.Is)) or not _literal(expected):
        return None
    if isinstance(compare.ops[0], ast.Is) and not (
        isinstance(expected, ast.Constant) and expected.value in (None, True, False)
        and type(expected.value) in (type(None), bool)
    ):
        return None
    if not isinstance(actual, ast.Call):
        return None
    name = dotted_name(actual.func)
    if (not name or name.split(".")[0] not in imports or name.split(".")[0] == "pytest"
            or not all(_literal(arg) for arg in actual.args)
            or not all(keyword.arg is not None and _literal(keyword.value) for keyword in actual.keywords)):
        return None
    return concrete


def _fixture(node):
    if (_args(node) != ["request"] or len(node.decorator_list) != 1 or len(node.body) != 1
            or not isinstance(node.body[0], ast.Return)
            or dotted_name(node.body[0].value) != "request.param"):
        return None
    decorator = node.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.fixture"
            or decorator.args or len(decorator.keywords) != 1 or decorator.keywords[0].arg != "params"):
        return None
    return decorator.keywords[0].value


def _test(node, fixtures, imports, *, baseline):
    names = _args(node)
    if names is None or not node.name.startswith("test"):
        return None
    body, bindings, table = node.body, [{}], False
    if baseline:
        if names or node.decorator_list:
            return None
    elif node.decorator_list:
        if len(node.decorator_list) != 1:
            return None
        decorator = node.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.mark.parametrize"
                or len(decorator.args) != 2 or decorator.keywords):
            return None
        columns = decorator.args[0]
        if isinstance(columns, ast.Constant) and isinstance(columns.value, str):
            columns = [name.strip() for name in columns.value.split(",")]
        elif isinstance(columns, (ast.List, ast.Tuple)) and all(
                isinstance(item, ast.Constant) and isinstance(item.value, str) for item in columns.elts):
            columns = [item.value for item in columns.elts]
        else:
            return None
        if not names or len(columns) != len(set(columns)) or set(columns) != set(names):
            return None
        bindings = _rows(decorator.args[1], columns, unpack=len(columns) != 1)
        table = True
    elif names:
        if (len(names) != 1 or names[0] not in fixtures or len(body) != 2
                or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1
                or not isinstance(body[0].value, ast.Name) or body[0].value.id != names[0]):
            return None
        columns = _names(body[0].targets[0])
        if not columns or names[0] in columns:
            return None
        bindings = _rows(fixtures[names[0]], columns, unpack=not isinstance(body[0].targets[0], ast.Name))
        body, table = body[1:], True
    elif ((len(body) == 1 and isinstance(body[0], ast.For))
          or (len(body) == 2 and isinstance(body[0], ast.Assign) and isinstance(body[1], ast.For))):
        loop = body[-1]
        rows = loop.iter
        if len(body) == 2:
            assignment = body[0]
            if (len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)
                    or not isinstance(rows, ast.Name) or rows.id != assignment.targets[0].id
                    or rows.id in imports):
                return None
            rows = assignment.value
        columns = _names(loop.target)
        if loop.orelse or not columns:
            return None
        bindings = _rows(rows, columns, unpack=not isinstance(loop.target, ast.Name))
        body, table = loop.body, True
    if bindings is None or len(body) != 1:
        return None
    assertions = [_concrete(body[0], row, imports) for row in bindings]
    if any(assertion is None for assertion in assertions):
        return None
    return [_Case(assertion, body[0], node) for assertion in assertions], table


def _module(source, *, baseline):
    if len(source) > MAX_SOURCE_BYTES:
        return None
    text = normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        return None
    imports, import_nodes, functions, names = set(), [], [], set()
    pytest_imported = False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not functions:
            if isinstance(node, ast.ImportFrom) and (node.level or any(alias.name == "*" for alias in node.names)):
                return None
            bound = [alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                     for alias in node.names]
            if names.intersection(bound) or len(set(bound)) != len(bound):
                return None
            names.update(bound)
            imports.update(bound)
            if (isinstance(node, ast.Import) and len(node.names) == 1
                    and node.names[0].name == "pytest" and node.names[0].asname is None):
                pytest_imported = True
            else:
                # Aliased pytest could be a shadowing decorator authority.
                if "pytest" in bound:
                    return None
                import_nodes.append(ast.dump(node, include_attributes=False))
        elif isinstance(node, ast.FunctionDef) and node.name not in names:
            names.add(node.name)
            functions.append(node)
        else:
            return None
    fixtures = {}
    if not baseline:
        for function in functions:
            fixture = _fixture(function)
            if fixture is not None:
                if not pytest_imported:
                    return None
                fixtures[function.name] = fixture
    result, table, used_fixtures = [], False, Counter()
    for function in functions:
        if function.name in fixtures:
            continue
        expanded = _test(function, fixtures, imports, baseline=baseline)
        if expanded is None:
            return None
        cases, is_table = expanded
        if function.decorator_list and not pytest_imported:
            return None
        used_fixtures.update(set(_args(function)) & fixtures.keys())
        result.extend(cases)
        table |= is_table and len(cases) >= 2
        if len(result) > MAX_CASES:
            return None
    if fixtures.keys() != used_fixtures.keys() or any(count != 1 for count in used_fixtures.values()):
        return None
    return text, import_nodes, result, table, pytest_imported


def _pytest_unshadowed(path, read):
    """Reject repository-local substitutes for the table decorator authority."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    directories = {"", "src"}
    directories.update("/".join(parts[:depth]) for depth in range(1, len(parts)))
    for directory in sorted(directories):
        prefix = directory + "/" if directory else ""
        if any(read(prefix + candidate) is not None for candidate in ("pytest.py", "pytest/__init__.py")):
            return False
    return True


def _project(parsed, text, cases):
    keys = Counter()
    definitions = []
    for case in cases:
        digest = hashlib.sha256(_subject_key(case).encode()).hexdigest()[:24]
        keys[digest] += 1
        name = f"test_concrete_{digest}_{keys[digest]}"
        definitions.append(f"def {name}():\n    {ast.unparse(case.assertion)}\n")
    concrete = parse_python("\n".join(definitions).encode(), collect_tests=True)
    offsets = _Offsets(text)
    units = []
    for unit, case in zip(concrete.units, cases):
        span = offsets.span(case.source_function)
        assertion = replace(unit.side.assertions[0], span=offsets.span(case.source_assertion))
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=[assertion])))
    return replace(parsed, units=units)


def _subject_key(case):
    compare = case.assertion.test
    return ast.dump(compare.left, include_attributes=False) + ":" + type(compare.ops[0]).__name__


def project_table_consolidation(before: bytes, after: bytes, before_parsed: ParsedFile, after_parsed: ParsedFile,
                                *, path: str, root_reader=None, root_searcher=None):
    """Project exact ordered subject coverage; leave expected edits detectable.

    The caller restricts this to one modified collected test file. Baseline
    tests are plain, zero-argument native single-assert functions; the head
    can consolidate them into literal parametrize, fixture(params=), or loops.
    Deleting/reordering rows, dynamic tables, indirect/marked params,
    setup/teardown, multiple assertions, and any executable module statement
    remain outside this first bounded implementation.
    """
    if (root_reader is None or root_searcher is None or not before_parsed.parse_ok or not after_parsed.parse_ok
            or len(before_parsed.units) < 2):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, baseline=True), _module(after, baseline=False)
        if old is None or new is None or old[1] != new[1] or not new[3]:
            return before_parsed, after_parsed
        old_keys = [_subject_key(case) for case in old[2]]
        new_keys = [_subject_key(case) for case in new[2]]
        # Extra literal cases can follow the complete old sequence. They
        # cannot run before an old oracle and change what it subsequently
        # sees; insertion/reordering stays outside the proof.
        if len(old_keys) < 2 or old_keys != new_keys[:len(old_keys)]:
            return before_parsed, after_parsed
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return before_parsed, after_parsed
    # A loop runs function-scope autouse fixtures once, while separate
    # functions run them once per case. An unchanged reset/mutator can
    # therefore invalidate the apparent same-oracle proof. Absence or
    # inertness of every test ancestor needs a strict snapshot reader.
    # Snapshot errors must escape the parser's unsupported-syntax fallback.
    if not inert_test_execution_context(path, root_reader, root_searcher):
        return before_parsed, after_parsed
    if new[4] and not _pytest_unshadowed(path, root_reader):
        return before_parsed, after_parsed
    return _project(before_parsed, old[0], old[2]), _project(after_parsed, new[0], new[2])
