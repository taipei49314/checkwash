from app.digits_only import digits_only


def test_mixed():
    assert digits_only("a1b2") == "12"
    assert digits_only("x4y") == "4"


def test_letters():
    assert digits_only("xyz") == ""


def test_digits():
    assert digits_only("42") == "42"
