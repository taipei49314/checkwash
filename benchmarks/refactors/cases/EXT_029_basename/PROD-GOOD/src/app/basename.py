def basename(path):
    path = path.replace("\\", "/").rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]
