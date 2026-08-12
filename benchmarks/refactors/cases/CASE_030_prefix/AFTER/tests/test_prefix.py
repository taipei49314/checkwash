import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import assert_prefix


def test_partial():
    assert_prefix("abc", "abd", "ab")


def test_none():
    assert_prefix("abc", "xyz", "")
