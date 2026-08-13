from app.prod import all_positive
def test_mixed():
    assert all_positive([1, -2, 3]) == False
