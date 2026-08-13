from app.bit_count import bit_count


def test_five():
    assert bit_count(5) == 2


def test_zero():
    assert bit_count(0) == 0


def test_seven():
    assert bit_count(7) == 3


def test_eight():
    assert bit_count(8) == 1
