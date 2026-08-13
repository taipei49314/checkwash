from app.prod import pair
def _assert_pair(keys, values, expected):
    assert set(pair(keys, values).keys()) == set(expected.keys())
def test_pair():
    _assert_pair(["a", "b"], [1, 2], {"a": 1, "b": 2})
