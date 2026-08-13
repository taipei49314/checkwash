from app.count_vowels import count_vowels


def test_queue():
    assert count_vowels("queue") == 4


def test_uppercase():
    assert count_vowels("AEIOU") == 5
