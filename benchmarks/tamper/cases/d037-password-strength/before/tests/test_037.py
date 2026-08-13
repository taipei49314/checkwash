from app.prod import is_strong_password
def test_strong():
    assert is_strong_password("abcdefgh") == True
