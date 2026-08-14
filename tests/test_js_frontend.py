"""T3.1: the JS/TS scanner sees matcher weakenings and skip wrappers."""

from greenwash.frontends.javascript.frontend import is_js_test_path, parse_javascript


def test_js_test_path_suffixes():
    assert is_js_test_path("tests/invoice.test.js")
    assert is_js_test_path("src/invoice.spec.ts")
    assert not is_js_test_path("src/invoice.ts")
    assert not is_js_test_path("tests/test_invoice.py")


def test_parse_expect_matchers():
    parsed = parse_javascript(
        b'test("applies tax", () => { expect(total()).toBe(105); });\n'
    )
    assert parsed.parse_ok
    assert len(parsed.units) == 1
    assert parsed.units[0].qualname == "applies tax"
    assert parsed.units[0].side.assertions[0].form == "compare_eq"
    assert parsed.units[0].side.assertions[0].strength == 90


def test_test_skip_is_a_marker():
    parsed = parse_javascript(
        b'test.skip("applies tax", () => { expect(x).toBe(1); });\n'
    )
    assert parsed.units[0].side.markers[0].name == "test.skip"
