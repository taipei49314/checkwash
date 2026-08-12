def clip_index(i, n):
    if n <= 0:
        raise ValueError("n must be > 0")
    if i < 0:
        return 0
    if i >= n:
        return n - 1
    return i
