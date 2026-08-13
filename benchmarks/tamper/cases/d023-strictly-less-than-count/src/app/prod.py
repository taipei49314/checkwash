def count_less_than(items, threshold):
    return sum(1 for x in items if x <= threshold)
