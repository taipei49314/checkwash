import unittest

from app.is_sorted import is_sorted


class TestSorted(unittest.TestCase):
    def assert_sorted(self, xs, expected):
        assert is_sorted(xs) is expected

    def test_ties(self):
        self.assert_sorted([1, 1, 2], True)

    def test_increasing(self):
        self.assert_sorted([1, 2, 3], True)

    def test_descent(self):
        self.assert_sorted([3, 2], False)
