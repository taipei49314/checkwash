from app.rpad import rpad


def assert_rpadded(s, width, fill, expected):
    got = rpad(s, width, fill)
    assert len(got) == max(len(s), width)
    assert got.startswith(s)
    assert got == expected


def test_short():
    assert_rpadded("hi", 5, ".", "hi...")


def test_already_wide():
    assert_rpadded("hello", 3, ".", "hello")
