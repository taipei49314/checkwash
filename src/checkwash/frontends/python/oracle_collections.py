"""Closed fresh-local collection idioms, not general mutation purity."""
import ast


def fresh_running_sum(body, parameters):
    """Only a fresh list is mutated; the scalar accumulator starts at zero."""
    if (len(parameters) != 1 or len(body) != 4 or not isinstance(body[0], ast.Assign)
            or not isinstance(body[1], ast.Assign) or not isinstance(body[2], ast.For)
            or len(body[0].targets) != 1 or len(body[1].targets) != 1
            or not all(isinstance(node, ast.Name) for node in (body[0].targets[0], body[1].targets[0], body[2].target))):
        return False
    values = parameters[0]
    output, accumulator, item = body[0].targets[0].id, body[1].targets[0].id, body[2].target.id
    if len({values, output, accumulator, item}) != 4:
        return False
    expected = ast.parse(f'''{output} = []
{accumulator} = 0
for {item} in {values}:
    {accumulator} += {item}
    {output}.append({accumulator})
return {output}
''')
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(expected)


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


def fresh_interleave(body, parameters):
    """The complete guarded append loop writes only its fresh result list."""
    if len(parameters) != 2 or len(body) != 4:
        return False
    first, second, loop, returned = body
    if (not isinstance(first, ast.Assign) or len(first.targets) != 1 or not isinstance(first.targets[0], ast.Name)
            or not isinstance(second, ast.Assign) or len(second.targets) != 1 or not isinstance(second.targets[0], ast.Name)
            or not isinstance(loop, ast.For) or not isinstance(loop.target, ast.Name)):
        return False
    output, limit, index = first.targets[0].id, second.targets[0].id, loop.target.id
    bindings = [*parameters, output, limit, index]
    if len(set(bindings)) != len(bindings) or {'max', 'len', 'range'} & set(bindings):
        return False
    left, right = parameters
    expected = ast.parse(f'''{output} = []
{limit} = max(len({left}), len({right}))
for {index} in range({limit}):
    if {index} < len({left}):
        {output}.append({left}[{index}])
    if {index} < len({right}):
        {output}.append({right}[{index}])
return {output}
''')
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(expected)


def fresh_unique_sequence(body, parameters):
    """An exact fresh-local stable deduplication loop over one sequence."""
    if len(parameters) != 1 or len(body) != 4:
        return False
    first, second, loop, returned = body
    if (not isinstance(first, ast.Assign) or len(first.targets) != 1 or not isinstance(first.targets[0], ast.Name)
            or not isinstance(second, ast.Assign) or len(second.targets) != 1 or not isinstance(second.targets[0], ast.Name)
            or not isinstance(loop, ast.For) or not isinstance(loop.target, ast.Name)):
        return False
    seen, output, item = first.targets[0].id, second.targets[0].id, loop.target.id
    bindings = [*parameters, seen, output, item]
    if len(set(bindings)) != len(bindings) or {'list', 'set'} & set(bindings):
        return False
    expected = ast.parse(f'''{seen} = set()
{output} = []
for {item} in {parameters[0]}:
    if {item} not in {seen}:
        {seen}.add({item})
        {output}.append({item})
return {output}
''')
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(expected)


def fresh_fill_none(body, parameters):
    """A fresh list selects existing primitive cells without mutating inputs."""
    if (len(parameters) != 2 or len(body) != 1 or not isinstance(body[0], ast.Return)
            or not isinstance(body[0].value, ast.ListComp) or len(body[0].value.generators) != 1
            or not isinstance(body[0].value.generators[0].target, ast.Name)):
        return False
    sequence, default = parameters
    item = body[0].value.generators[0].target.id
    if len({sequence, default, item}) != 3:
        return False
    expected = ast.parse(f'return [{default} if {item} is None else {item} for {item} in {sequence}]')
    return ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(expected)
