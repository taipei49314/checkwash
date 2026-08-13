def common_suffix(a, b):
    i = 0
    n = min(len(a), len(b))
    while i < n and a[-1 - i] == b[-1 - i]:
        i += 1
    return a[len(a) - i :]
