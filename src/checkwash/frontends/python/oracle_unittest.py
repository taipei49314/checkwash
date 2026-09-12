"""Expand a closed TestCase lifecycle only when the caller proves purity.

Default unittest collection sorts method names. setUp checks are repeated
before every test. Explicit lifecycle calls remain unsupported. No callback,
state, custom dispatch or external base class is silently removed.

The caller requires exact oracle multiplicity and pure imported subjects on
both sides. With preserved expectations, the suite passes exactly when all
of those deterministic checks pass. This is suite-verdict equivalence, not
call-order equivalence: a failing setup or assertion still prevents later
statements in its method from executing.
"""

import ast
import copy


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
    if (not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name)
            or call.func.value.id != 'self' or call.func.attr not in {'assertEqual', 'assertIs'}
            or len(call.args) != 2 or call.keywords):
        return statement
    assertion = ast.Assert(test=ast.Compare(left=call.args[0],
                                            ops=[ast.Eq() if call.func.attr == 'assertEqual' else ast.Is()],
                                            comparators=[call.args[1]]), msg=None)
    return ast.copy_location(assertion, statement)


def expand_unittest_classes(tree):
    authority, expanded = False, set()
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
        for member in node.body:
            if isinstance(member, ast.Pass) or (isinstance(member, ast.Expr)
                    and isinstance(member.value, ast.Constant) and isinstance(member.value.value, str)):
                continue
            if not _plain_method(member) or member.name in names:
                return None
            names.add(member.name)
            if not (member.name == 'setUp' or member.name.startswith(('test', 'check', 'assert_'))):
                return None
            member.body = [_assertion(statement) for statement in member.body]
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
            expanded.add('test_' + node.name + '__' + method.name)
        node.body = [method for method in methods if not method.name.startswith('test')] + tests
        node.bases = []
    return expanded
