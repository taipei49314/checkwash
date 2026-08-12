from app.slugify import slugify


def test_slugify():
    code = compile("assert slugify('Hi There') == 'hi-there'", "<oracle>", "exec")
    exec(code, {"slugify": slugify})
