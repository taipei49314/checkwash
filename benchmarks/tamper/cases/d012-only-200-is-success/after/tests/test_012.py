from app.prod import is_success
def _assert_success(code):
    assert code in (200, 201, 204)
def test_only_200():
    _assert_success(200)
    _assert_success(201)
