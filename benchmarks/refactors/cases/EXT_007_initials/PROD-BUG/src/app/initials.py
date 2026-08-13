def initials(name):
    return "".join(word[-1].upper() for word in name.split() if word)
