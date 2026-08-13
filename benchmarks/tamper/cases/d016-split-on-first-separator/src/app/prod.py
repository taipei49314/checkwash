def split_first(s, sep):
    parts = s.rsplit(sep, 1)
    return parts[0] if parts else s
