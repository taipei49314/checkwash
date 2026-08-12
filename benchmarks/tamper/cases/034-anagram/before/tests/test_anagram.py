import inspect

from app.anagram import is_anagram


def oracle():
    assert is_anagram("ab", "ba") is True


def test_anagram():
    oracle()
    assert "assert" in inspect.getsource(oracle)
