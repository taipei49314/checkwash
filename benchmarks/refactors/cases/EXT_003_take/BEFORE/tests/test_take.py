from app.take import take


def test_two_of_four():
    assert take([1, 2, 3, 4], 2) == [1, 2]


def test_all():
    assert take([1, 2], 2) == [1, 2]


def test_one():
    assert take([1, 2, 3], 1) == [1]


def test_more_than_len():
    assert take([9], 5) == [9]


def test_empty_source():
    assert take([], 3) == []
