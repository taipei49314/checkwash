from app.prod import join_names
def _assert_joined(names, expected):
    assert join_names(names) == expected + ","
def test_join():
    _assert_joined(["a", "b"], "a, b")
