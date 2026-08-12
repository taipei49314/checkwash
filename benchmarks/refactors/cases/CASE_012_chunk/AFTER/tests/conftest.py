import pytest

from app.chunk import chunk


@pytest.fixture
def assert_chunks():
    def _check(xs, n, expected):
        assert chunk(xs, n) == expected

    return _check
