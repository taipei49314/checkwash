def indent(text, n):
    pad = " " * n
    lines = text.split("\n")
    lines[0] = pad + lines[0]
    return "\n".join(lines)
