import pytest

from app.hamming import hamming


@pytest.fixture
def assert_hamming():
    def _check(a, b, expected):
        assert hamming(a, b) == expected

    return _check
