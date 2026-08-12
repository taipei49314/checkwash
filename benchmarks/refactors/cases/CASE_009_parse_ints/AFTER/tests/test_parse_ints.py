from contextlib import contextmanager

from app.parse_ints import parse_ints


@contextmanager
def expect(expected):
    box = {}
    yield box
    assert box["got"] == expected


def test_csv():
    with expect([1, 2, 3]) as box:
        box["got"] = parse_ints("1,2,3")


def test_spaces():
    with expect([1, 2, 3]) as box:
        box["got"] = parse_ints("1 2 3")
