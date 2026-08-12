def fib(n):
    if n < 0:
        raise ValueError("n must be >= 0")
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a
