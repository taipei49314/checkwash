def rotate(xs, k):
    if not xs:
        return []
    k %= len(xs)
    return xs[k:] + xs[:k]
