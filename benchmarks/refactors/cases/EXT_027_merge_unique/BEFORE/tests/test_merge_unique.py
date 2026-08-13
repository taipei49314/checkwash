from app.merge_unique import merge_unique


def test_overlap():
    assert merge_unique([1, 2], [2, 3]) == [1, 2, 3]


def test_order():
    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]
