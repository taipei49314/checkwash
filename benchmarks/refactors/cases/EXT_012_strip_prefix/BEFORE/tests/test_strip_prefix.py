from app.strip_prefix import strip_prefix


def test_hit():
    assert strip_prefix("foobar", "foo") == "bar"


def test_miss():
    assert strip_prefix("foobar", "baz") == "foobar"


def test_empty_prefix():
    assert strip_prefix("ab", "") == "ab"
