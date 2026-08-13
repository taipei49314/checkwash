from app.prod import Stack
class StackTestBase:
    def make_stack(self):
        return Stack()
class TestStack(StackTestBase):
    def test_lifo(self):
        s = self.make_stack()
        s.push(1)
        s.push(2)
        assert s.pop() == 1
class TestStackEdge:
    def test_empty_pop(self):
        s = Stack()
        try:
            s.pop()
            assert False
        except IndexError:
            pass
