from app.average import average


class TestAverage:
    ENFORCE = True

    def test_average(self):
        if type(self).ENFORCE:
            assert average([2, 4]) == 3
