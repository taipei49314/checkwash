import pytest
from app.prod import is_valid_email
@pytest.fixture
def valid_email():
    return "user@example.com"
def test_consecutive_dots():
    assert is_valid_email("user..name@example.com")
def test_normal(valid_email):
    assert is_valid_email(valid_email) == True
