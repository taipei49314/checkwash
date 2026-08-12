def test_even(assert_chunks):
    assert_chunks([1, 2, 3, 4], 2, [[1, 2], [3, 4]])


def test_remainder(assert_chunks):
    assert_chunks([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]])
