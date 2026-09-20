"""Expand a closed TestCase lifecycle only when the caller proves purity.

Default unittest collection sorts method names. setUp checks are repeated
before every test. Explicit lifecycle calls remain unsupported. Immutable
literal row providers are expanded only at fully accounted loop consumers;
callbacks, other state, custom dispatch and external bases remain unproved.

The caller requires pure imported subjects on both sides. General lifecycle
changes retain exact oracle multiplicity; an after-suite of only default
subTest loops may add rows because failures still continue to every original
check. With preserved expectations, the suite passes exactly when all
of those deterministic checks pass. This is suite-verdict equivalence, not
call-order equivalence: a failing setup or assertion still prevents later
statements in its method from executing.
"""

import ast
import copy

from checkwash.frontends.python.unittest_tables import expand_class_tables


def _plain_method(node):
    if not isinstance(node, ast.FunctionDef):
        return False
    args = node.args
    return (not node.decorator_list and not node.returns and not getattr(node, 'type_params', ())
            and not args.posonlyargs and not args.kwonlyargs and not args.defaults
            and not args.vararg and not args.kwarg and args.args and args.args[0].arg == 'self'
            and not any(arg.annotation for arg in args.args))


def _assertion(statement):
    if isinstance(statement, ast.Assert):
        return statement
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return statement
    call = statement.value
    if (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id == 'self' and call.func.attr == 'assertTrue'
            and len(call.args) == 1 and not call.keywords and isinstance(call.args[0], ast.Compare)
            and len(call.args[0].ops) == 1 and isinstance(call.args[0].ops[0], (ast.Eq, ast.Is))):
        # Default assertTrue applies the same truth test as a native assert.
        # Keep the complete comparison and operator; the caller still owns
        # TestCase authority, primitive source purity and exact multiplicity.
        return ast.copy_location(ast.Assert(test=copy.deepcopy(call.args[0]), msg=None), statement)
    if (not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name)
            or call.func.value.id != 'self' or call.func.attr not in {'assertEqual', 'assertIs'}
            or len(call.args) != 2 or call.keywords):
        return statement
    assertion = ast.Assert(test=ast.Compare(left=call.args[0],
                                            ops=[ast.Eq() if call.func.attr == 'assertEqual' else ast.Is()],
                                            comparators=[call.args[1]]), msg=None)
    return ast.copy_location(assertion, statement)


def _subtest_loop(statement):
    """Default subTest preserves suite failure for each deterministic row.

    Only inert diagnostic keyword values are admitted. The caller verifies
    the class has no overrides, both subjects are pure, and oracle counts
    match before allowing changed assertion continuation after a failure.
    """
    if (not isinstance(statement, ast.For) or statement.orelse or len(statement.body) != 1
            or not isinstance(statement.iter, (ast.List, ast.Tuple))
            or not isinstance(statement.target, ast.Tuple)
            or not all(isinstance(item, ast.Name) for item in statement.target.elts)):
        return statement
    names = {item.id for item in statement.target.elts}
    block = statement.body[0]
    if not isinstance(block, ast.With) or len(block.items) != 1 or len(block.body) != 1:
        return statement
    context = block.items[0]
    call = context.context_expr
    if (context.optional_vars is not None or not isinstance(call, ast.Call) or call.args
            or not isinstance(call.func, ast.Attribute) or call.func.attr != 'subTest'
            or not isinstance(call.func.value, ast.Name) or call.func.value.id != 'self'
            or any(keyword.arg is None or not (
                isinstance(keyword.value, ast.Name) and keyword.value.id in names
                or isinstance(keyword.value, ast.Constant) and type(keyword.value.value) in (str, int, bool, type(None))
            ) for keyword in call.keywords)):
        return statement
    assertion = _assertion(block.body[0])
    if not isinstance(assertion, ast.Assert) or assertion.msg is not None:
        return statement
    statement.body = [assertion]
    statement._checkwash_subtest = True
    return statement


def expand_unittest_classes(tree):
    authority, expanded = False, set()
    subtest_only = True
    for node in tree.body:
        if isinstance(node, ast.Import) and len(node.names) == 1:
            authority |= node.names[0].name == 'unittest' and node.names[0].asname is None
        if not (isinstance(node, ast.ClassDef) and any(
            isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
            and base.value.id == 'unittest' and base.attr == 'TestCase' for base in node.bases
        )):
            continue
        if (not authority or len(node.bases) != 1 or node.decorator_list or node.keywords
                or getattr(node, 'type_params', ()) or not node.name.startswith('Test')):
            return None
        methods, setup = [], []
        names = set()
        expand_class_tables(node, tree)
        for member in node.body:
            if isinstance(member, ast.Pass) or (isinstance(member, ast.Expr)
                    and isinstance(member.value, ast.Constant) and isinstance(member.value.value, str)):
                continue
            if not _plain_method(member) or member.name in names:
                return None
            names.add(member.name)
            if not (member.name == 'setUp' or member.name.startswith(('test', 'check', 'assert_'))):
                return None
            member.body = [_subtest_loop(_assertion(statement)) for statement in member.body]
            if member.name == 'setUp':
                if len(member.args.args) != 1 or not member.body or not all(
                        isinstance(statement, ast.Assert) and statement.msg is None for statement in member.body):
                    return None
                setup = member.body
            else:
                methods.append(member)
        tests = sorted([method for method in methods if method.name.startswith('test')], key=lambda method: method.name)
        if not tests or len(setup) > 64:
            return None
        for method in tests:
            if len(method.args.args) != 1:
                return None
            method.body = copy.deepcopy(setup) + method.body
            subtest_only &= (not setup and len(method.body) == 1
                             and getattr(method.body[0], '_checkwash_subtest', False))
            expanded.add('test_' + node.name + '__' + method.name)
        node.body = [method for method in methods if not method.name.startswith('test')] + tests
        node.bases = []
    return expanded, bool(expanded) and subtest_only
