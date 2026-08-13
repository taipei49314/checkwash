def merge_unique(a, b):
    out = []
    seen = set()
    for x in list(a) + list(b):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
