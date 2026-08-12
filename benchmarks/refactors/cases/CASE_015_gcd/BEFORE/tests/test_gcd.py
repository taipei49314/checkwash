from app.gcd import gcd


def test_negatives():
    assert gcd(-6, -9) == 3


def test_coprime():
    assert gcd(8, 9) == 1
