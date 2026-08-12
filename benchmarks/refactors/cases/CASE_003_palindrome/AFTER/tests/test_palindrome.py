from app.palindrome import is_palindrome


def assert_is_palindrome(text, expected):
    assert is_palindrome(text) is expected


def test_mixed_case():
    assert_is_palindrome("Aba", True)


def test_phrase():
    assert_is_palindrome("Never odd or even", True)


def test_negative():
    assert_is_palindrome("xyz", False)
