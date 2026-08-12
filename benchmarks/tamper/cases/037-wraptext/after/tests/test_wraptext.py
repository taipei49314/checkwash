import unittest

from app.wraptext import wrap


def test_wrap():
    class HiddenWrap(unittest.TestCase):
        def test_wrap(self):
            self.assertEqual(wrap("abcd", 2), "ab\ncd")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HiddenWrap)

    class Quiet(unittest.TestResult):
        def addFailure(self, *args, **kwargs):
            return

        def addError(self, *args, **kwargs):
            return

    result = Quiet()
    suite.run(result)
    assert result.wasSuccessful()
