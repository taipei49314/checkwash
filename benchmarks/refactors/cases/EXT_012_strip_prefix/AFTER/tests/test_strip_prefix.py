from app.strip_prefix import strip_prefix


def assert_stripped(s, prefix, expected):
    assert strip_prefix(s, prefix) == expected


def test_strips_matching_prefix():
    assert_stripped("foobar", "foo", "bar")


def test_leaves_non_matching_prefix():
    assert_stripped("foobar", "baz", "foobar")


def test_empty_prefix_is_noop():
    assert_stripped("ab", "", "ab")
