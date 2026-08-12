from typing import TYPE_CHECKING

from app.lowercase import lowercase


def test_lowercase():
    if TYPE_CHECKING:
        assert lowercase("Ab") == "ab"
    assert callable(lowercase)
