from app.min_max import min_max


def test_mixed():
    assert_span([3, 1, 2], (1, 3))


def test_negative():
    assert_span([-5, 0], (-5, 0))


def test_singleton():
    assert_span([7], (7, 7))


def assert_span(xs, expected):
    assert min_max(xs) == expected
