from app.cap_words import cap_words


def test_two_words():
    assert cap_words("hello WORLD") == "Hello World"


def test_single():
    assert cap_words("hI") == "Hi"
