from app.median import median


class MedianChecks:
    def check_odd(self):
        assert median([1, 3, 2]) == 2

    def check_even(self):
        assert median([1, 2, 3, 4]) == 2.5


class TestMedian(MedianChecks):
    def test_odd(self):
        self.check_odd()

    def test_even(self):
        self.check_even()
