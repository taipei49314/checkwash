from app.ceil_div import ceil_div


def test_rounds_up():
    assert ceil_div(5, 2) == 3


def test_exact():
    assert ceil_div(4, 2) == 2


def test_small_numerator():
    assert ceil_div(1, 3) == 1
