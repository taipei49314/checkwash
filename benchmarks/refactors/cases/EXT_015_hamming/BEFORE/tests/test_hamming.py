from app.hamming import hamming


def test_classic():
    assert hamming("karolin", "kathrin") == 3


def test_all_different():
    assert hamming("000", "111") == 3


def test_identical():
    assert hamming("abc", "abc") == 0
