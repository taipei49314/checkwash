from app.basename import basename


def assert_names(rows):
    for path, expected in rows:
        assert basename(path) == expected


def test_basenames():
    assert_names(
        [
            ("a/b/c.txt", "c.txt"),
            ("file", "file"),
            ("dir/sub/", "sub"),
        ]
    )
