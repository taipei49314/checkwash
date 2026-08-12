import operator

from app.safe_div import safe_div


def check_eq(got, expected):
    assert operator.eq(got, expected)


def check_is(got, expected):
    assert operator.is_(got, expected)


def test_ok():
    check_eq(safe_div(6, 3), 2)


def test_zero_divisor():
    check_is(safe_div(1, 0), None)
