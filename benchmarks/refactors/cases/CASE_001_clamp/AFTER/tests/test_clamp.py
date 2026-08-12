from app.clamp import clamp


def assert_clamped(n, lo, hi, expected):
    assert clamp(n, lo, hi) == expected


def test_below():
    assert_clamped(-5, 0, 10, 0)


def test_inside():
    assert_clamped(5, 0, 10, 5)


def test_above():
    assert_clamped(15, 0, 10, 10)
