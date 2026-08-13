def indent(text, n):
    pad = " " * n
    return "\n".join(pad + line for line in text.split("\n"))
