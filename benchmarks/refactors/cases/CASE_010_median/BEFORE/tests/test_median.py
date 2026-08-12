from app.median import median


def test_odd():
    assert median([1, 3, 2]) == 2


def test_even():
    assert median([1, 2, 3, 4]) == 2.5
