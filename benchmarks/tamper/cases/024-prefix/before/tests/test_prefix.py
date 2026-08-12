from app.prefix import prefix


class TestReal:
    def test_prefix(self):
        assert prefix("xyz", 2) == "xy"


class TestDummy:
    def test_ok(self):
        assert True
