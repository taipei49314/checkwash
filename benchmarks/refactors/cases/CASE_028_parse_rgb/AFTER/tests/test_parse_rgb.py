from collections import namedtuple

from app.parse_rgb import parse_hex_rgb

RGB = namedtuple("RGB", "r g b")


def test_white():
    assert parse_hex_rgb("#ffffff") == RGB(255, 255, 255)


def test_red():
    assert parse_hex_rgb("ff0000") == RGB(255, 0, 0)
