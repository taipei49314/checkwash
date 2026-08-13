from app.unquote import unquote


def test_double():
    assert unquote('"hello"') == "hello"


def test_single():
    assert unquote("'hi'") == "hi"


def test_plain():
    assert unquote("hello") == "hello"
