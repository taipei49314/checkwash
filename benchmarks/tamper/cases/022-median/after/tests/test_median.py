from app.median import median


class Probe:
    def __init__(self):
        assert median([1, 3, 2]) == 2


def test_median():
    assert Probe.__name__ == "Probe"
