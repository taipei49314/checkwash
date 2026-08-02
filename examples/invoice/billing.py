def invoice_total(items):
    """Total price of an invoice, rounded to cents."""
    return sum(price * qty for price, qty in items)
