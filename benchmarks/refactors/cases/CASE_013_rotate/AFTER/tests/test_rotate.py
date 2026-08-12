from app.rotate import rotate


def check(xs, k, expected):
    assert rotate(xs, k) == expected


def test_rotate():
    check([1, 2, 3, 4], 1, [4, 1, 2, 3])
    check([1, 2, 3, 4], 2, [3, 4, 1, 2])
