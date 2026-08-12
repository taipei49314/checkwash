from app.biggest import biggest


def test_biggest():
    cases = [([1, 2, 3], 3), ([9, 0, 4], 9)]
    cases = []
    for xs, expected in cases:
        assert biggest(xs) == expected
