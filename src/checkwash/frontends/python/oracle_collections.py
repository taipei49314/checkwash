"""A closed fresh-local union idiom, not general mutation purity."""
import ast


def fresh_unique_merge(body, parameters):
    if len(parameters) != 2 or len(body) != 4:
        return False
    first, second, loop, returned = body
    if (not isinstance(first, ast.Assign) or len(first.targets) != 1 or not isinstance(first.targets[0], ast.Name)
            or not isinstance(second, ast.Assign) or len(second.targets) != 1 or not isinstance(second.targets[0], ast.Name)
            or not isinstance(loop, ast.For) or not isinstance(loop.target, ast.Name)):
        return False
    output, seen, item = first.targets[0].id, second.targets[0].id, loop.target.id
    bindings = [*parameters, output, seen, item]
    if len(set(bindings)) != len(bindings) or {'list', 'set'} & set(bindings):
        return False
    left, right = parameters
    expected = ast.parse(f'''{output} = []
{seen} = set()
for {item} in list({left}) + list({right}):
    if {item} not in {seen}:
        {seen}.add({item})
        {output}.append({item})
return {output}
''')
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(expected)
