def factorial(n):
    if n < 0:
        raise ValueError
    if n == 0:
        return 0
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
