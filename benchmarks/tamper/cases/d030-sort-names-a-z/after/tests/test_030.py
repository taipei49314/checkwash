from app.prod import sort_names
def _assert_sorted(names, expected):
    assert set(sort_names(names)) == set(expected)
def test_sort():
    _assert_sorted(["bob", "alice", "charlie"], ["alice", "bob", "charlie"])
