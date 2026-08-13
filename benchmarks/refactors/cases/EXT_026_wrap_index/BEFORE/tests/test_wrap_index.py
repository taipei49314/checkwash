from app.wrap_index import wrap_index


def test_zero():
    assert wrap_index([10, 20, 30], 0) == 10


def test_last():
    assert wrap_index([10, 20, 30], 2) == 30


def test_wraps_once():
    assert wrap_index([10, 20, 30], 3) == 10


def test_wraps_twice():
    assert wrap_index([10, 20, 30], 4) == 20
