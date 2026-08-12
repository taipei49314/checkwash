def median(xs):
    if not xs:
        raise ValueError("empty")
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    return ys[mid]
