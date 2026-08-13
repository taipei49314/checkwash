from app.abs_diff import abs_diff


def test_negative_delta():
    assert abs_diff(3, 10) == 7


def test_positive_delta():
    assert abs_diff(10, 3) == 7
