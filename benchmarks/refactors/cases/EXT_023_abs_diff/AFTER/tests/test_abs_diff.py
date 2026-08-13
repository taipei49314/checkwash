from app.abs_diff import abs_diff


def test_negative_delta():
    assert_diff(3, 10, 7)


def test_positive_delta():
    assert_diff(10, 3, 7)


def assert_diff(a, b, expected):
    assert abs_diff(a, b) == expected
