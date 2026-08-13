from app.is_prefix import is_prefix


def test_prefix():
    assert is_prefix("foobar", "foo") is True


def test_suffix_is_not_prefix():
    assert is_prefix("foobar", "bar") is False


def test_exact():
    assert is_prefix("ab", "ab") is True


def test_longer():
    assert is_prefix("ab", "abc") is False


def test_empty():
    assert is_prefix("", "") is True
