from app.bit_count import bit_count


def assert_bits(n, expected):
    assert bit_count(n) == expected


def test_popcount_five():
    assert_bits(5, 2)


def test_popcount_zero():
    assert_bits(0, 0)


def test_popcount_seven():
    assert_bits(7, 3)


def test_popcount_eight():
    assert_bits(8, 1)
