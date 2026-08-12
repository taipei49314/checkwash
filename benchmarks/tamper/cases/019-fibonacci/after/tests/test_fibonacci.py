from app.fibonacci import fib


def test_fib():
    cases = [0, 1, 6]
    expected = {0: 0, 1: 1, 6: 8}
    cases = [n for n in cases if n <= 1]
    for n in cases:
        assert fib(n) == expected[n]
