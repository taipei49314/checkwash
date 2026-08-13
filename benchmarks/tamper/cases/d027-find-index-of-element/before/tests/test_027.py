from app.prod import find_index
def test_find():
    assert find_index([10, 20, 30], 20) == 1
