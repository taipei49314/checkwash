import pytest

from app.leap import is_leap


@pytest.fixture(params=[(1900, False), (2000, True), (2024, True)])
def leap_case(request):
    return request.param


def test_leap(leap_case):
    year, expected = leap_case
    assert is_leap(year) is expected
