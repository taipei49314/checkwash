def rpad(s, width, fill=" "):
    if len(s) >= width:
        return s
    return fill * (width - len(s)) + s
