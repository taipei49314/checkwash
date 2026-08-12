from app.parsebool import parsebool


def test_parsebool():
    check = True
    if check:
        assert parsebool("false") is False
