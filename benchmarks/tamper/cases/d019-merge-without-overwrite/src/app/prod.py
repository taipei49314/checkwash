def merge_dicts(base, override):
    result = base.copy()
    result.update(override)
    return result
