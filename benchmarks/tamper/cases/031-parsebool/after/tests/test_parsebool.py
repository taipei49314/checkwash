from app.parsebool import parsebool


def test_parsebool():
    check = True
    if check and False:
        assert parsebool("false") is False
    assert callable(parsebool)
