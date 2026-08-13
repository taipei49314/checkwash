from app.prod import get_config
def _assert_config(key, configs, expected):
    result = get_config(key, configs)
    assert result is expected
def test_missing_raises():
    _assert_config("missing", {}, None)
