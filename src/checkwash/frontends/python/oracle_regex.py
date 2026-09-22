"""Two closed regex string idioms; callers prove standard-library authority."""
import ast


def closed_regex_body(body, parameters):
    if len(parameters) != 1 or parameters[0] in {'re', 'int'}:
        return False
    value = parameters[0]
    patterns = [f'''{value} = {value}.lower().strip()
{value} = re.sub(r"[^a-z0-9]+", "-", {value})
return {value}.strip("-")
''']
    if (len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1
            and isinstance(body[0].targets[0], ast.Name) and isinstance(body[1], ast.Return)
            and isinstance(body[1].value, ast.ListComp) and len(body[1].value.generators) == 1
            and isinstance(body[1].value.generators[0].target, ast.Name)):
        parts, item = body[0].targets[0].id, body[1].value.generators[0].target.id
        if len({value, parts, item, 're', 'int'}) == 5:
            patterns.append(f'''{parts} = re.split(r"[,\\s]+", {value}.strip())
return [int({item}) for {item} in {parts} if {item}]
''')
    candidate = ast.dump(ast.Module(body=body, type_ignores=[]))
    return any(candidate == ast.dump(ast.parse(pattern)) for pattern in patterns)
