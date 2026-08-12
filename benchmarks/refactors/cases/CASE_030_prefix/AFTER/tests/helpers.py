from app.prefix import common_prefix


def assert_prefix(a, b, expected):
    assert common_prefix(a, b) == expected
