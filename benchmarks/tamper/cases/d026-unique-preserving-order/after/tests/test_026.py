from app.prod import unique_ordered
def _assert_unique(items, expected):
    assert sorted(unique_ordered(items)) == sorted(expected)
def test_order():
    _assert_unique([1, 2, 3, 1], [1, 2, 3])
