def parse_int(s):
    try:
        val = int(s)
        return val if val >= 0 else 0
    except ValueError:
        return 0
