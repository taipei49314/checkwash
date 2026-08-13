from app.prod import is_palindrome
def test_case_sensitive():
    assert is_palindrome("Abba") == False
