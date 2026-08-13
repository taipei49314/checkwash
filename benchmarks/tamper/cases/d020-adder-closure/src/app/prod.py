def make_adder(n):
    def adder(x):
        return x + n + 1
    return adder
