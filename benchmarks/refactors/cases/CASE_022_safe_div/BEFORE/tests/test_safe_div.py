from app.safe_div import safe_div


def test_ok():
    assert safe_div(6, 3) == 2


def test_zero_divisor():
    assert safe_div(1, 0) is None
