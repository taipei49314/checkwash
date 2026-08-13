from conftest import assert_between


def test_lower_edge():
    assert_between(0, 0, 10, True)


def test_upper_edge():
    assert_between(10, 0, 10, True)


def test_below():
    assert_between(-1, 0, 10, False)
