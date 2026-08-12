import pytest

from app.startswith import starts_with


@pytest.fixture(autouse=True)
def verify_prefix():
    yield
    assert starts_with("abc", "z") is False


def test_starts_with():
    starts_with("abc", "z")
