from app.prod import divide
def _assert_divide(a, b, expected):
    assert abs(divide(a, b) - expected) < 1
def test_ten_div_three():
    _assert_divide(10, 3, 3)
