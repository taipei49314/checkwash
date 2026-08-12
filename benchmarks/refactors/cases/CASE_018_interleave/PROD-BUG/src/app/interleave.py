def interleave(a, b):
    out = []
    n = min(len(a), len(b))
    for i in range(n):
        out.append(a[i])
        out.append(b[i])
    return out
