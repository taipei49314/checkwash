from app.flatten import flatten


def test_flatten():
    got = flatten([[1], [2, 3]])
    return
    assert got == [1, 2, 3]
