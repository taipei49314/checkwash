from app.factorial import factorial


def test_zero():
    assert factorial(0) == 1


def test_one():
    assert factorial(1) == 1


def test_five():
    assert factorial(5) == 120
