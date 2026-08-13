from app.percent import percent


def test_quarter():
    assert percent(1, 4) == 25


def test_half():
    assert percent(1, 2) == 50


def test_all():
    assert percent(3, 3) == 100
