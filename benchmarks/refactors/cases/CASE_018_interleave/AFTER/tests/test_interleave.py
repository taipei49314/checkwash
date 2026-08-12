from app.interleave import interleave


class Asserter:
    def pair(self, a, b, expected):
        assert interleave(a, b) == expected


def test_equal_length():
    Asserter().pair([1, 2], ["a", "b"], [1, "a", 2, "b"])


def test_uneven():
    Asserter().pair([1, 2, 3], ["a"], [1, "a", 2, 3])
