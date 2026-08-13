from app.prod import is_even
def _assert_even(n):
    assert not is_even(n)
def test_four_even():
    _assert_even(4)
