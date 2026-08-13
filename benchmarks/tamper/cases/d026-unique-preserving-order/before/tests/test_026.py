from app.prod import unique_ordered
def test_order():
    assert unique_ordered([1, 2, 3, 1]) == [1, 2, 3]
