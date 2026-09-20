"""Closed string-literal methods; never evaluate repository expressions."""
import ast


def literal_string_replace(node):
    """Return a bounded literal for str.replace with entirely literal operands.

    A string literal has the interpreter's exact str type, so neither lookup
    nor replacement invokes a repository object's methods. Keep dynamic
    receivers, arguments, keywords and oversized results outside this proof.
    """
    if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
            or node.func.attr != 'replace' or node.keywords or len(node.args) not in (2, 3)):
        return None
    values = [node.func.value, *node.args[:2]]
    if not all(isinstance(value, ast.Constant) and type(value.value) is str
               and len(value.value) <= 4096 for value in values):
        return None
    count = -1
    if len(node.args) == 3:
        count_node, sign = node.args[2], 1
        if isinstance(count_node, ast.UnaryOp) and isinstance(count_node.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(count_node.op, ast.USub) else 1
            count_node = count_node.operand
        if not isinstance(count_node, ast.Constant) or type(count_node.value) is not int:
            return None
        count = sign * count_node.value
        if not -4096 <= count <= 4096:
            return None
    receiver, old, new = [value.value for value in values]
    occurrences = receiver.count(old)
    if count >= 0:
        occurrences = min(occurrences, count)
    if len(receiver) + occurrences * (len(new) - len(old)) > 4096:
        return None
    return ast.Constant(value=receiver.replace(old, new, count))
