from app.prod import merge_dicts
def _assert_merged(base, override, key):
    result = merge_dicts(base, override)
    assert key in result
def test_no_overwrite():
    _assert_merged({"a": 1}, {"a": 99}, "a")
