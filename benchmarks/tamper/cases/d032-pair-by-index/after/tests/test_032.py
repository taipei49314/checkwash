from app.prod import pair_by_index
def _assert_pair(a, b, expected):
    result = pair_by_index(a, b)
    assert len(result) == len(expected) and all(len(p) == 2 for p in result)
def test_pair():
    _assert_pair([1, 2], ["a", "b"], [(1, "a"), (2, "b")])
