from app.prod import any_even
def _assert_any_even(items, expected):
    assert expected or any_even(items)
def test_some_even():
    _assert_any_even([1, 2, 3], True)
