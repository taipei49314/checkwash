from app.common_suffix import common_suffix


def assert_suffix(a, b, expected):
    assert common_suffix(a, b) == expected
