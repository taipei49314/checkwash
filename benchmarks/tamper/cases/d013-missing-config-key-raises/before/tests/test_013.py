from app.prod import get_config
def test_missing_raises():
    try:
        get_config("missing", {})
        assert False
    except KeyError:
        pass
