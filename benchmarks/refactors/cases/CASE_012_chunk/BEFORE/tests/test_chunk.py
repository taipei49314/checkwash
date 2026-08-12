from app.chunk import chunk


def test_even():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
