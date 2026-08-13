def hamming(a, b):
    if len(a) != len(b):
        raise ValueError("length mismatch")
    return sum(x != y for x, y in zip(a, b))
