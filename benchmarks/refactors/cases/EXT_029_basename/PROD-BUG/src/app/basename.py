def basename(path):
    path = path.replace("\\", "/").rstrip("/")
    if not path:
        return ""
    return path.split("/")[0]
