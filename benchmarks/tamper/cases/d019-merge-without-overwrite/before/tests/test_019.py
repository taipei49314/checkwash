from app.prod import merge_dicts
def test_no_overwrite():
    assert merge_dicts({"a": 1}, {"a": 99})["a"] == 1
