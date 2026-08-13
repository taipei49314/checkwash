from app.prod import make_filename
def test_filename():
    assert make_filename("doc", "txt") == "doc.txt"
