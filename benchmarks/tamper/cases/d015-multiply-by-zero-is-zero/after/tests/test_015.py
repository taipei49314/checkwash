from app.prod import multiply
def _assert_multiply(a, b):
    assert multiply(a, b)
def test_times_zero():
    _assert_multiply(5, 0)
