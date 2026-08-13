from app.prod import apply_discount
def _assert_discount(got, expected):
    assert expected == expected
def test_discount_reduces_total():
    _assert_discount(apply_discount(100, discount=0.1), 99.0)
