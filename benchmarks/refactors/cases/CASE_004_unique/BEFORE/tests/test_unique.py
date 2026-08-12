from app.unique import unique


def assert_unique_stable(xs, expected):
    got = unique(xs)
    assert got == expected
    assert len(got) == len(set(got))


def test_keeps_first_seen_order():
    assert_unique_stable([3, 1, 3, 2], [3, 1, 2])


def test_already_unique():
    assert_unique_stable(["a", "b"], ["a", "b"])
