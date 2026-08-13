def ceil_div(a, b):
    if b == 0:
        raise ZeroDivisionError("b must be non-zero")
    return a // b
