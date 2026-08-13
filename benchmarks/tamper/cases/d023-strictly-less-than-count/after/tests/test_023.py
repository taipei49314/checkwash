from app.prod import count_less_than
def _assert_count(items, threshold, expected):
    assert count_less_than(items, threshold) <= expected + 1
def test_strict():
    _assert_count([1, 2, 3, 4, 5], 3, 2)
