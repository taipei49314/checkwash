from app.palindrome import is_palindrome


def assert_pal(text, expected):
    assert is_palindrome(text) is expected


def test_mixed_case():
    assert_pal("Aba", True)


def test_phrase():
    assert_pal("Never odd or even", True)


def test_negative():
    assert_pal("xyz", False)
