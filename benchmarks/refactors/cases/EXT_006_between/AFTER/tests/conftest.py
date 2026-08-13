from app.between import between


def assert_between(x, lo, hi, expected):
    assert between(x, lo, hi) is expected
