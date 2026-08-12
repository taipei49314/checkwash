from app.flatten import flatten


def test_mixed():
    if flatten([[1, 2], 3]) != [1, 2, 3]:
        raise AssertionError("expected one-level flatten")


def test_flat():
    if flatten([1, 2]) != [1, 2]:
        raise AssertionError("expected unchanged flat list")
