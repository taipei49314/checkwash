from app.is_sorted import is_sorted


def test_ties():
    assert is_sorted([1, 1, 2]) is True


def test_increasing():
    assert is_sorted([1, 2, 3]) is True


def test_descent():
    assert is_sorted([3, 2]) is False
