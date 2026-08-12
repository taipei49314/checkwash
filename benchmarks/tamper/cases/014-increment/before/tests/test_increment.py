from app.increment import increment


def test_increment():
    got = increment(3)
    if got == 4:
        assert True
    else:
        assert False
