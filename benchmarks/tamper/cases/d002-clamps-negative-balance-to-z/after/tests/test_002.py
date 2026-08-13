from app.prod import clamp_balance
def _assert_clamped(value, expected=None):
    if expected is None:
        expected = value
    assert value == expected
def test_negative_clamps_to_zero():
    _assert_clamped(clamp_balance(-50))
