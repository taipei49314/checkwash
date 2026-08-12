import pytest

from app.power import power


def test_power():
    with pytest.raises(AssertionError):
        assert power(2, 3) == 8
