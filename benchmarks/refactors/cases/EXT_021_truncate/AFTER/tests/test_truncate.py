from app.truncate import truncate


def assert_trunc(s, n):
    expected = s if len(s) <= n else s[:n] + "..."
    assert truncate(s, n) == expected


def test_short():
    assert_trunc("hello", 10)


def test_cut():
    assert_trunc("hello", 3)


def test_empty():
    assert_trunc("", 0)
