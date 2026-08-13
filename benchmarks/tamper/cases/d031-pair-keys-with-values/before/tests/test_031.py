from app.prod import pair
def test_pair():
    assert pair(["a", "b"], [1, 2]) == {"a": 1, "b": 2}
