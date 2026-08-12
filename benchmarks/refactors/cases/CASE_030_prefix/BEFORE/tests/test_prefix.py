from app.prefix import common_prefix


def test_partial():
    assert common_prefix("abc", "abd") == "ab"


def test_none():
    assert common_prefix("abc", "xyz") == ""
