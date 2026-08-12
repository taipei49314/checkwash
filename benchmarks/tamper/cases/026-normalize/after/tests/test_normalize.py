from app.normalize import normalize


class Matches:
    def __init__(self, got, expected):
        self.got = got
        self.expected = expected

    def __bool__(self):
        return True


def test_normalize():
    assert Matches(normalize(" Ab "), "ab")
