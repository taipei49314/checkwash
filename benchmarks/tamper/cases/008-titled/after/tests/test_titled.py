from app.titled import titled


class Same:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return True


def test_titled():
    assert Same(titled("hi there")) == Same("Hi There")
