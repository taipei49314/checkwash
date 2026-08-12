from app.addsub import add


def assert_sum(got, expected):
    assert got == expected


def test_add():
    assert_sum(add(2, 3), 5)
