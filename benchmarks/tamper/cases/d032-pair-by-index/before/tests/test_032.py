from app.prod import pair_by_index
def test_pair():
    assert pair_by_index([1, 2], ["a", "b"]) == [(1, "a"), (2, "b")]
