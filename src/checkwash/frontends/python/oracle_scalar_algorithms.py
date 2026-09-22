"""Complete scalar algorithm bodies with no escaping writes or callbacks."""
import ast


def _same(body, expected):
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(ast.parse(expected))


def closed_euclidean(body, parameters):
    """Absolute-value normalization makes both loop registers immutable numbers."""
    if len(parameters) != 2 or len(body) != 3 or len(set(parameters)) != 2 or 'abs' in parameters:
        return False
    left, right = parameters
    return _same(body, f'''{left}, {right} = abs({left}), abs({right})
while {right}:
    {left}, {right} = {right}, {left} % {right}
return {left}
''')


def closed_ordinal(body, parameters):
    """A literal mapping chooses a string suffix for primitive formatting."""
    if (len(parameters) != 1 or len(body) != 2 or not isinstance(body[0], ast.If)
            or not body[0].body or not isinstance(body[0].body[0], ast.Assign)
            or len(body[0].body[0].targets) != 1 or not isinstance(body[0].body[0].targets[0], ast.Name)):
        return False
    value, suffix = parameters[0], body[0].body[0].targets[0].id
    if value == suffix:
        return False
    return _same(body, f'''if 10 <= {value} % 100 <= 13:
    {suffix} = "th"
else:
    {suffix} = {{1: "st", 2: "nd", 3: "rd"}}.get({value} % 10, "th")
return f"{{{value}}}{{{suffix}}}"
''')
