import re
def is_valid_email(email):
    pattern = r'^[^@]+@[^@]+\.[^@]+$'
    return bool(re.match(pattern, email))
