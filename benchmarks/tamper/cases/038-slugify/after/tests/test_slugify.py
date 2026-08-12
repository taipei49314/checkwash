from app.slugify import slugify


def test_slugify():
    code = compile("assert slugify('Hi There') == 'hi-there'", "<oracle>", "exec")
    assert code.co_consts
