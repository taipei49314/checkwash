from app.prod import count_less_than
def test_strict():
    assert count_less_than([1, 2, 3, 4, 5], 3) == 2
