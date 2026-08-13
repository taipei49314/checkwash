def rpad(s, width, fill=" "):
    if len(s) >= width:
        return s
    return s + fill * (width - len(s))
