from app.prod import is_valid_email
def test_consecutive_dots():
    assert is_valid_email("user..name@example.com") == False
