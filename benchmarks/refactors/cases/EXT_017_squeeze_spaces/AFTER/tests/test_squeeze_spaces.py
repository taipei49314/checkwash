from app.squeeze_spaces import squeeze_spaces


def assert_squeezed(s, expected):
    got = squeeze_spaces(s)
    assert "  " not in got
    assert " " in got
    assert got == expected


def test_multi():
    assert_squeezed("a   b  c", "a b c")


def test_already_single():
    assert_squeezed("x y", "x y")
