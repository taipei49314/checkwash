def is_sorted(xs):
    return all(xs[i] < xs[i + 1] for i in range(len(xs) - 1))
