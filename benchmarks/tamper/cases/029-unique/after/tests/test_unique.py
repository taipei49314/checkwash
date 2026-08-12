from app.unique import unique


def test_unique():
    pred = lambda: unique([1, 1, 2]) == [1, 2]
    assert pred
