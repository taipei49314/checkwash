from app.product import product


def test_three():
    assert product([2, 3, 4]) == 24


def test_empty():
    assert product([]) == 1


def test_singleton():
    assert product([7]) == 7
