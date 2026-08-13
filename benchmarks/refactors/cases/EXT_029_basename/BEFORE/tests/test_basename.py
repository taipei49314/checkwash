from app.basename import basename


def test_nested():
    assert basename("a/b/c.txt") == "c.txt"


def test_bare():
    assert basename("file") == "file"


def test_trailing_slash():
    assert basename("dir/sub/") == "sub"
