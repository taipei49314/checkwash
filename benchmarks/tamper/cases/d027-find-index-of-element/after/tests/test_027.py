from app.prod import find_index
def _assert_find(items, target, expected):
    result = find_index(items, target)
    assert bool(result) == bool(expected)
def test_find():
    _assert_find([10, 20, 30], 20, 1)
