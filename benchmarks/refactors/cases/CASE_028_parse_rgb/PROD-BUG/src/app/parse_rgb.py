def parse_hex_rgb(s):
    s = s.lstrip("#")
    return int(s[0], 16), int(s[1], 16), int(s[2], 16)
