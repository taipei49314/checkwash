from contextlib import contextmanager

from app.clamp import clamp


@contextmanager
def checking(got, expected):
    yield
    assert got == expected


def test_clamp():
    with checking(clamp(10, 0, 5), 5):
        pass
