from app.count_vowels import count_vowels


def assert_eq(got, expected):
    assert got == expected


def test_queue():
    assert_eq(count_vowels("queue"), 4)


def test_uppercase():
    assert_eq(count_vowels("AEIOU"), 5)
