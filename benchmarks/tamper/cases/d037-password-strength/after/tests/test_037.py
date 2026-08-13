from app.prod import is_strong_password
def _assert_strong(pwd):
    assert not is_strong_password(pwd)
def test_strong():
    _assert_strong("abcdefgh")
