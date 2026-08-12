import functools

from app.cap_words import cap_words


def expect(expected):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper():
            assert fn() == expected

        return wrapper

    return deco


@expect("Hello World")
def test_two_words():
    return cap_words("hello WORLD")


@expect("Hi")
def test_single():
    return cap_words("hI")
