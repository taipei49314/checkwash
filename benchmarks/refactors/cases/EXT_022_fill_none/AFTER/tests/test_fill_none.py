from app.fill_none import fill_none


def assert_filled(xs, default, expected):
    assert fill_none(xs, default) == expected


def test_middle():
    assert_filled([1, None, 2], 0, [1, 0, 2])


def test_only_none():
    assert_filled([None], 0, [0])


def test_keeps_zero():
    assert fill_none([0, 1], 9) == [0, 1]
