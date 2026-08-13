def strip_prefix(s, prefix):
    if s.startswith(prefix):
        return s[len(prefix):]
    return s
