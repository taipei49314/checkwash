from app.normalize import normalize


def test_collapse_and_lower():
    assert normalize("  Hello   WORLD  ") == "hello world"


def test_already_clean():
    assert normalize("ok") == "ok"
