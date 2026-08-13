from app.prod import safe_divide
def test_div_zero():
    try:
        safe_divide(1, 0)
        assert False
    except ZeroDivisionError:
        pass
