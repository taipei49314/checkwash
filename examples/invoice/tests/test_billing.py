from billing import invoice_total


def test_invoice_total():
    # two items: 10.005 x 3 and 2.675 x 2 -> 35.365 -> rounds to 35.37
    assert invoice_total([(10.005, 3), (2.675, 2)]) == 35.37
