import pytest

from app.is_prefix import is_prefix


@pytest.mark.parametrize(
    "s, prefix, expected",
    [
        ("foobar", "foo", True),
        ("foobar", "bar", False),
        ("ab", "ab", True),
        ("ab", "abc", False),
        ("", "", True),
    ],
)
def test_is_prefix(s, prefix, expected):
    assert is_prefix(s, prefix) is expected
