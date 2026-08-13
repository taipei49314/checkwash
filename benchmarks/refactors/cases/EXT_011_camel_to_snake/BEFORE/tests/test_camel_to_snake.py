from app.camel_to_snake import camel_to_snake


def test_foo_bar():
    assert camel_to_snake("fooBar") == "foo_bar"


def test_http():
    assert camel_to_snake("getHTTP") == "get_h_t_t_p"


def test_already():
    assert camel_to_snake("already") == "already"
