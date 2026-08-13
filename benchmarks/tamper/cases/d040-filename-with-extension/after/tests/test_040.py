from app.prod import make_filename
def _assert_filename(name, ext, expected):
    assert make_filename(name, ext).endswith(f".{ext}")
def test_filename():
    _assert_filename("doc", "txt", "doc.txt")
