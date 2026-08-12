from app.digit_sum import digit_sum


def test_positive():
    assert digit_sum(12) == 3


def test_negative():
    assert digit_sum(-12) == 3
