from app.rpad import rpad


def test_short():
    got = rpad("hi", 5, ".")
    assert len(got) == 5
    assert got.startswith("hi")
    assert got == "hi..."


def test_already_wide():
    got = rpad("hello", 3, ".")
    assert len(got) == 5
    assert got.startswith("hello")
    assert got == "hello"
