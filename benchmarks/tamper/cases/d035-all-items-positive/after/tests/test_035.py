from app.prod import all_positive
def _assert_all_positive(items):
    assert all_positive(items)
def test_mixed():
    _assert_all_positive([1, -2, 3])
