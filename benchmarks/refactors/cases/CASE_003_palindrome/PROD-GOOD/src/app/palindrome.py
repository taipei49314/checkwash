def is_palindrome(s):
    folded = "".join(ch.lower() for ch in s if ch.isalnum())
    return folded == folded[::-1]
