from app.pair_sum import pair_sum


def test_basic():
    assert pair_sum([1, 2], [3, 4]) == [4, 6]


def test_zeros():
    assert pair_sum([0, 5], [1, 1]) == [1, 6]


def test_singleton():
    assert pair_sum([10], [2]) == [12]
