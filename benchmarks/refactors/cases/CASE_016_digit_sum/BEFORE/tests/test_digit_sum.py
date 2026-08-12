import unittest

from app.digit_sum import digit_sum


class TestDigitSum(unittest.TestCase):
    def test_positive(self):
        assert digit_sum(12) == 3

    def test_negative(self):
        assert digit_sum(-12) == 3
