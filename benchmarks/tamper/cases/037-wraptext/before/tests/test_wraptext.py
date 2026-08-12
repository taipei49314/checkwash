import unittest

from app.wraptext import wrap


def test_wrap():
    class HiddenWrap(unittest.TestCase):
        def test_wrap(self):
            self.assertEqual(wrap("abcd", 2), "ab\ncd")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HiddenWrap)
    result = unittest.TestResult()
    suite.run(result)
    assert result.wasSuccessful()
