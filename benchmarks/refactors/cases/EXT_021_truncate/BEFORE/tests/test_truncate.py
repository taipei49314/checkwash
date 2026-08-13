from app.truncate import truncate


def test_short():
    assert truncate("hello", 10) == "hello"


def test_cut():
    assert truncate("hello", 3) == "hel..."


def test_empty():
    assert truncate("", 0) == ""
