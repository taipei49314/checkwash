from app.palindrome import is_pal


class Holder:
    @property
    def ok(self):
        assert is_pal("ab") is False
        return True


def test_is_pal():
    assert Holder().ok
