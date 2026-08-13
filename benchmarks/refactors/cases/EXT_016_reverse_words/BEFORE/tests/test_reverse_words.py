from app.reverse_words import reverse_words


def test_two_words():
    assert reverse_words("hello world") == "world hello"


def test_three():
    assert reverse_words("a b c") == "c b a"


def test_one():
    assert reverse_words("one") == "one"
