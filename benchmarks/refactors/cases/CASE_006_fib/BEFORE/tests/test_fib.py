import pytest

from app.fib import fib


@pytest.mark.parametrize("n, expected", [(0, 0), (1, 1), (6, 8)])
def test_fib(n, expected):
    assert fib(n) == expected
