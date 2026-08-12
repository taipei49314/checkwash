import unittest

from app.anagram import is_anagram


class TestAnagram(unittest.TestCase):
    def test_mixed_case(self):
        self.assertEqual(is_anagram("Listen", "Silent"), True)

    def test_negative(self):
        self.assertTrue(is_anagram("abc", "ab") is False)
