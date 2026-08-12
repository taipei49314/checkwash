from app.windows import windows


def check(xs, n, idx, expected):
    assert windows(xs, n)[idx] == expected


def test_windows():
    check([1, 2, 3, 4], 2, 0, [1, 2])
    check([1, 2, 3, 4], 2, -1, [3, 4])
