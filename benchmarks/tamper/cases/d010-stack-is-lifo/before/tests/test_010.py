from app.prod import Stack
def test_lifo():
    s = Stack()
    s.push(1)
    s.push(2)
    assert s.pop() == 2
