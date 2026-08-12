import pytest

from app.slugify import slugify


@pytest.fixture
def slugged():
    assert slugify("Hello World") == "hello-world"
    return slugify


def test_punctuation(slugged):
    assert slugged("Hello, World!") == "hello-world"
