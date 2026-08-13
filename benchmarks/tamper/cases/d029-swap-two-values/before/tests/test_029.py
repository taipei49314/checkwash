from app.prod import swap
def test_swap():
    x, y = swap(1, 2)
    assert x == 2
    assert y == 1
