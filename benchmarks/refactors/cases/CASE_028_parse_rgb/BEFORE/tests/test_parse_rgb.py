from app.parse_rgb import parse_hex_rgb


def test_white():
    r, g, b = parse_hex_rgb("#ffffff")
    assert r == 255
    assert g == 255
    assert b == 255


def test_red():
    r, g, b = parse_hex_rgb("ff0000")
    assert r == 255
    assert g == 0
    assert b == 0
