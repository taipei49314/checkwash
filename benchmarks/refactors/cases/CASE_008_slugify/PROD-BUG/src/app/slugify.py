import re


def slugify(s):
    s = s.strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
