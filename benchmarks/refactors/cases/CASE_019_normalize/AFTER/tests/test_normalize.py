import pytest

from app.normalize import normalize


@pytest.fixture
def checked_norm():
    calls = []

    def run(s):
        result = normalize(s)
        calls.append(result)
        return result

    yield run
    assert "hello world" in calls


def test_collapse_and_lower(checked_norm):
    checked_norm("  Hello   WORLD  ")


def test_already_clean():
    assert normalize("ok") == "ok"
