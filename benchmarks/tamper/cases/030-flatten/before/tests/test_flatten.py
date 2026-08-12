from app.flatten import flatten


def test_flatten():
    got = flatten([[1], [2, 3]])
    assert got == [1, 2, 3]
