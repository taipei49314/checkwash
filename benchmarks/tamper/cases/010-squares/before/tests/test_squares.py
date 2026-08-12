from app.squares import square


def test_square():
    checks = (square(i) == i * i for i in range(2, 5))
    assert all(checks)
