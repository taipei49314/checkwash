import functools

from app.unquote import unquote


def expect(expected):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper():
            assert fn() == expected

        return wrapper

    return deco


@expect("hello")
def test_double():
    return unquote('"hello"')


@expect("hi")
def test_single():
    return unquote("'hi'")


@expect("hello")
def test_plain():
    return unquote("hello")
