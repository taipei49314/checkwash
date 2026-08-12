from app.all_equal import all_equal


def test_empty():
    assert all_equal([]) is True


def test_same():
    assert all_equal([2, 2, 2]) is True


def test_diff():
    assert all_equal([1, 2]) is False
