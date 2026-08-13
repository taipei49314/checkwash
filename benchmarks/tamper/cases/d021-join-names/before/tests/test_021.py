from app.prod import join_names
def test_join():
    assert join_names(["a", "b"]) == "a, b"
