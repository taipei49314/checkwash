from app.windows import windows


def test_first_window():
    assert windows([1, 2, 3, 4], 2)[0] == [1, 2]


def test_last_window():
    assert windows([1, 2, 3, 4], 2)[-1] == [3, 4]
