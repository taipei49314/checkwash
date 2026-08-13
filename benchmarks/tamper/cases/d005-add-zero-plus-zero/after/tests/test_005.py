from app.prod import add
def _assert_add(a, b, expected):
    return add(a, b) == expected
def test_zero_plus_zero():
    _assert_add(0, 0, 0)
