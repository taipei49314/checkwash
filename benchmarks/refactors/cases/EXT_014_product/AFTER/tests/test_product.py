import math

from app.product import product


def assert_product(xs):
    assert product(xs) == math.prod(xs)


def test_three():
    assert_product([2, 3, 4])


def test_empty():
    assert_product([])


def test_singleton():
    assert_product([7])
