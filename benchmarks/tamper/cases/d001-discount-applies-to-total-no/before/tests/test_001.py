from app.prod import apply_discount
def test_discount_reduces_total():
    assert apply_discount(100, discount=0.1) == 99.0
