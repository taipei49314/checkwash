import unittest

from app.flatten import flatten


class TestFlatten(unittest.TestCase):
    def test_mixed(self):
        self.assertEqual(flatten([[1, 2], 3]), [1, 2, 3])

    def test_flat(self):
        self.assertEqual(flatten([1, 2]), [1, 2])
