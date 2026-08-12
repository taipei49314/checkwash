import pytest

from app.power import power


def test_power():
    assert power(2, 3) == 8
