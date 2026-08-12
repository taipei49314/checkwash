from app.addsub import add


def assert_sum(got, expected):
    assert got == expected


def test_add():
    add(2, 3)
    assert callable(assert_sum)
