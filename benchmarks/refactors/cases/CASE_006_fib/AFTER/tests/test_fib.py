from app.fib import fib

CASES = [(0, 0), (1, 1), (6, 8)]


def test_fib():
    for n, expected in CASES:
        assert fib(n) == expected
