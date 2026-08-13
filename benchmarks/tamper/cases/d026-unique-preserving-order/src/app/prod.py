def unique_ordered(items):
    seen = set()
    result = []
    for item in reversed(items):
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
