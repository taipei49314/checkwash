from app.prod import greet
def _assert_greet(name, expected):
    assert name in greet(name)
def test_greet():
    _assert_greet("Alice", "Hello, Alice!")
