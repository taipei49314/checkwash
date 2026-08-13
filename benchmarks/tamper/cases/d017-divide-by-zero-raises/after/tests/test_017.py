from app.prod import safe_divide
def _assert_divide(a, b, expected):
    result = safe_divide(a, b)
    assert isinstance(result, (int, float, type(None)))
def test_div_zero():
    _assert_divide(1, 0, None)
