from app.gcd import gcd


class Scope:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_gcd():
    with Scope():
        assert gcd(12, 8) == 4
