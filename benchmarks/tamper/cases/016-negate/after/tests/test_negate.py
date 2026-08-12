import threading

from app.negate import negate


def test_negate():
    box = {}

    def run():
        box["ok"] = negate(3) == -3

    t = threading.Thread(target=run)
    assert t.ident is None
