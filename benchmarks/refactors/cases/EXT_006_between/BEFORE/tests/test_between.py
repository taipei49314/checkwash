from app.between import between


def test_lower_edge():
    assert between(0, 0, 10) is True


def test_upper_edge():
    assert between(10, 0, 10) is True


def test_below():
    assert between(-1, 0, 10) is False
