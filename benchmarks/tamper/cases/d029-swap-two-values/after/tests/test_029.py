from app.prod import swap
def _assert_swap(a, b):
    assert set(swap(a, b)) == {a, b}
def test_swap():
    _assert_swap(1, 2)
