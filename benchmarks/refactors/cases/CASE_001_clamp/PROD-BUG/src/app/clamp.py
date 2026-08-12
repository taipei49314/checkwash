def clamp(n, lo, hi):
    if n < lo:
        return hi
    if n > hi:
        return lo
    return n
