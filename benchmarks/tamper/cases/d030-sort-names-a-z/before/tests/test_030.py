from app.prod import sort_names
def test_sort():
    assert sort_names(["bob", "alice", "charlie"]) == ["alice", "bob", "charlie"]
