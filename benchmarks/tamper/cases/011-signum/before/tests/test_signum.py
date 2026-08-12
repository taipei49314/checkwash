import unittest

from app.signum import sign


class TestSign(unittest.TestCase):
    def test_sign(self):
        cases = [(-2, -1), (0, 0), (3, 1)]
        for x, expected in cases:
            with self.subTest(x=x):
                self.assertEqual(sign(x), expected)
