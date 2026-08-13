import pytest

from app.percent import percent


@pytest.fixture
def assert_pct():
    def _check(n, total, expected):
        assert percent(n, total) == expected

    return _check


def test_quarter(assert_pct):
    assert_pct(1, 4, 25)


def test_half(assert_pct):
    assert_pct(1, 2, 50)


def test_all(assert_pct):
    assert_pct(3, 3, 100)
