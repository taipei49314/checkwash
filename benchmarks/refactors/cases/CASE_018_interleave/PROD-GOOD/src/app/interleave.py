def interleave(a, b):
    out = []
    n = max(len(a), len(b))
    for i in range(n):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out
