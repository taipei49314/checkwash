def camel_to_snake(s):
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
