def test_classic(assert_hamming):
    assert_hamming("karolin", "kathrin", 3)


def test_all_different(assert_hamming):
    assert_hamming("000", "111", 3)


def test_identical(assert_hamming):
    assert_hamming("abc", "abc", 0)
