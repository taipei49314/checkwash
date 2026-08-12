from app.clamp0 import clamp0


def test_clamp0():
    while True:
        assert clamp0(-3) == 0
        break
