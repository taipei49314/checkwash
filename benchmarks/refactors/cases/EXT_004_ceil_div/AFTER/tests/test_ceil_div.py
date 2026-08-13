from app.ceil_div import ceil_div


def assert_ceil(a, b):
    assert ceil_div(a, b) == (a + b - 1) // b


def test_rounds_up():
    assert_ceil(5, 2)


def test_exact():
    assert_ceil(4, 2)


def test_small_numerator():
    assert_ceil(1, 3)
