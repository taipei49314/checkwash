from app.prod import clamp_balance
def test_negative_clamps_to_zero():
    assert clamp_balance(-50) == 0
