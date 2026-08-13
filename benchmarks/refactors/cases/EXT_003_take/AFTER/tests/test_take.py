from app.take import take


def assert_taken(xs, n, expected):
    assert take(xs, n) == expected


def test_two_of_four():
    assert_taken([1, 2, 3, 4], 2, [1, 2])


def test_all():
    assert_taken([1, 2], 2, [1, 2])


def test_one():
    assert_taken([1, 2, 3], 1, [1])


def test_more_than_len():
    assert_taken([9], 5, [9])


def test_empty_source():
    assert_taken([], 3, [])
