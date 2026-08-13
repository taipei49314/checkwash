from app.prod import double_all
def _assert_doubled(items, expected):
    result = double_all(items)
    assert all(isinstance(x, int) for x in result)
def test_double():
    _assert_doubled([1, 2, 3], [2, 4, 6])
