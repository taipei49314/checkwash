import pytest

from app.startswith import starts_with


@pytest.fixture
def verify_prefix():
    yield
    assert starts_with("abc", "z") is False


def test_starts_with():
    starts_with("abc", "z")
