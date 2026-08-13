def apply_discount(subtotal, tax_rate=0.1, discount=0.0):
    tax = subtotal * tax_rate
    discounted = subtotal * (1 - discount)
    return discounted + tax
