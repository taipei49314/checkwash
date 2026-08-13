import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import assert_suffix


def test_overlap():
    assert_suffix("abc", "xbc", "bc")


def test_none():
    assert_suffix("abc", "xyz", "")


def test_same():
    assert_suffix("same", "same", "same")
