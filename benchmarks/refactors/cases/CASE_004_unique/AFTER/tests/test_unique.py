from app.unique import unique


def assert_result(xs, expected):
    assert unique(xs) == expected


def assert_no_duplicates(xs):
    got = unique(xs)
    assert len(got) == len(set(got))


def test_keeps_first_seen_order():
    assert_result([3, 1, 3, 2], [3, 1, 2])
    assert_no_duplicates([3, 1, 3, 2])


def test_already_unique():
    assert_result(["a", "b"], ["a", "b"])
    assert_no_duplicates(["a", "b"])
