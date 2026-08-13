from app.prod import filter_positive
def test_filter():
    assert filter_positive([-1, 0, 1, 2, -3]) == [1, 2]
