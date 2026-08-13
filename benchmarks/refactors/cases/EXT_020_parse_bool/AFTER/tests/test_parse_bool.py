import pytest

from app.parse_bool import parse_bool


@pytest.fixture
def check():
    def _check(s, expected):
        assert parse_bool(s) is expected

    return _check


def test_yes(check):
    check("Yes", True)


def test_true_upper(check):
    check("TRUE", True)


def test_no(check):
    check("no", False)
