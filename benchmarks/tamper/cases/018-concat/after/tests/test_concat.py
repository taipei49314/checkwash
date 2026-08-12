from app.concat import concat


def test_concat():
    cases = [("a", "b", "ab"), ("x", "y", "xy")]
    stream = iter(cases)
    list(stream)
    for a, b, expected in stream:
        assert concat(a, b) == expected
