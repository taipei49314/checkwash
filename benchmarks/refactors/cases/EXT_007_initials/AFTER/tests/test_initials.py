import pytest

from app.initials import initials


@pytest.fixture
def assert_initials():
    def _check(name, expected):
        assert initials(name) == expected

    return _check


def test_two_words(assert_initials):
    assert_initials("john doe", "JD")


def test_single(assert_initials):
    assert_initials("Ada", "A")


def test_three(assert_initials):
    assert_initials("John Quincy Adams", "JQA")
