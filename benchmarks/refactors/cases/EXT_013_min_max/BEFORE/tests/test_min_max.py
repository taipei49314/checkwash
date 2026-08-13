from app.min_max import min_max


def test_mixed():
    assert min_max([3, 1, 2]) == (1, 3)


def test_negative():
    assert min_max([-5, 0]) == (-5, 0)


def test_singleton():
    assert min_max([7]) == (7, 7)
