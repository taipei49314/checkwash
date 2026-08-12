from typing import TYPE_CHECKING

from app.lowercase import lowercase


def test_lowercase():
    assert lowercase("Ab") == "ab"
    if TYPE_CHECKING:
        assert lowercase("Ab") == "ab"
