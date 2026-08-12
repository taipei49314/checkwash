import unittest

from app.rotate import rotate


class TestRotate(unittest.TestCase):
    def test_rotate(self):
        self.assertEqual(rotate([1, 2, 3], 1), [2, 3, 1])
