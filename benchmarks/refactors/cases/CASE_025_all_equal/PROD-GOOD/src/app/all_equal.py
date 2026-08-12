def all_equal(xs):
    return all(x == xs[0] for x in xs) if xs else True
