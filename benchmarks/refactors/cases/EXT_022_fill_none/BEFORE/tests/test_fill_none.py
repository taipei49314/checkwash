from app.fill_none import fill_none


def test_middle():
    assert fill_none([1, None, 2], 0) == [1, 0, 2]


def test_only_none():
    assert fill_none([None], 0) == [0]


def test_keeps_zero():
    assert fill_none([0, 1], 9) == [0, 1]
