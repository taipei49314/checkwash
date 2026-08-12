from app.clipstr import clipstr


class Bag:
    def __init__(self, *items):
        self.items = items

    def __contains__(self, item):
        return item in self.items


def test_clipstr():
    assert clipstr("hello", 2) in Bag("he")
