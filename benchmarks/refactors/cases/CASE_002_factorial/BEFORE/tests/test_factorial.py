from app.factorial import factorial


def assert_fact(n, expected):
    assert factorial(n) == expected


def test_zero():
    assert_fact(0, 1)


def test_one():
    assert_fact(1, 1)


def test_five():
    assert_fact(5, 120)
