from app.leap import is_leap


def test_century_non_leap():
    assert is_leap(1900) is False


def test_400():
    assert is_leap(2000) is True


def test_ordinary():
    assert is_leap(2024) is True
