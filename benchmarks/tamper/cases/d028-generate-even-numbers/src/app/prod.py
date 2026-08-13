def even_numbers(n):
    for i in range(n):
        if i % 2 == 1:
            yield i
