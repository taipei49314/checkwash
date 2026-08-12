from app.expand_range import expand_range


def test_spans():
    assert expand_range(1, 3) == [1, 2, 3]
    assert expand_range(5, 5) == [5]
