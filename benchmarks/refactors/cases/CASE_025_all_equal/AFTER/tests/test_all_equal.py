from app.all_equal import all_equal


def check(xs, pred):
    assert pred(all_equal(xs))


def test_empty():
    check([], lambda r: r is True)


def test_same():
    check([2, 2, 2], lambda r: r is True)


def test_diff():
    check([1, 2], lambda r: r is False)
