def parse_name(s):
    parts = s.split()
    if len(parts) == 1:
        return {"first": parts[0], "last": ""}
    return {"first": parts[0], "last": parts[-1]}
