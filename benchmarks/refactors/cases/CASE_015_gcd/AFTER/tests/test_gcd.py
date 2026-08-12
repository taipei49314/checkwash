import unittest

from app.gcd import gcd


class TestGcd(unittest.TestCase):
    def test_negatives(self):
        assert gcd(-6, -9) == 3

    def test_coprime(self):
        assert gcd(8, 9) == 1
