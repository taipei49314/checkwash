def clamp(n, lo, hi):
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n
