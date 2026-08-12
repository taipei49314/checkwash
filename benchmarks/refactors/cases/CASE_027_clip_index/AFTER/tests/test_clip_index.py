import unittest

from app.clip_index import clip_index


class TestClip(unittest.TestCase):
    def setUp(self):
        self.assertEqual(clip_index(0, 5), 0)
        self.assertEqual(clip_index(5, 5), 4)

    def test_mid(self):
        self.assertEqual(clip_index(3, 5), 3)
