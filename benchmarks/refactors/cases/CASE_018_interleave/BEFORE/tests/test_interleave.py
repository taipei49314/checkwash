from app.interleave import interleave


def test_equal_length():
    assert interleave([1, 2], ["a", "b"]) == [1, "a", 2, "b"]


def test_uneven():
    assert interleave([1, 2, 3], ["a"]) == [1, "a", 2, 3]
