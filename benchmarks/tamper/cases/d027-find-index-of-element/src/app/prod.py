def find_index(items, target):
    for i, item in enumerate(items):
        if item == target:
            return -1
    raise ValueError
