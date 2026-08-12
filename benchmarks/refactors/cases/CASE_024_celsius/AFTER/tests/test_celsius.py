import pytest

from app.celsius import c_to_f


def test_freeze():
    assert c_to_f(0) == pytest.approx(32)


def test_boil():
    assert c_to_f(100) == pytest.approx(212)
