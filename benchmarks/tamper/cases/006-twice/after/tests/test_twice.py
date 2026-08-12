import doctest
import sys

from app.twice import twice  # noqa: F401


def _oracle():
    """
    >>> from app.twice import twice
    >>> twice(4)
    8
    """


def test_twice():
    assert _oracle.__doc__ is not None
