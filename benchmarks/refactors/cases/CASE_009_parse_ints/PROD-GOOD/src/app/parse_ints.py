import re


def parse_ints(s):
    parts = re.split(r"[,\s]+", s.strip())
    return [int(p) for p in parts if p]
