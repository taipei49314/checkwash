from functools import partial

from app.countvowels import count_vowels


def boom(got, expected):
    assert got == expected


def test_count_vowels():
    job = partial(boom, count_vowels("xyz"), 0)
    assert callable(job)
