def digits_only(s):
    return "".join(ch for ch in s if not ch.isdigit())
