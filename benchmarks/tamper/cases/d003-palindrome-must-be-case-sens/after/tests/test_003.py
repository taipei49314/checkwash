from app.prod import is_palindrome
def _assert_palindrome(s):
    assert is_palindrome(s)
def test_case_sensitive():
    _assert_palindrome("Abba")
