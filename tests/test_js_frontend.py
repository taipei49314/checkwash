"""T3.1: the JS/TS scanner sees matcher weakenings and skip wrappers."""

from checkwash.detectors.test_disabled import detect
from checkwash.frontends.javascript.frontend import is_js_test_path, parse_javascript
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import DiffGlobals, IR

# Issue #156: `split("\n")` contains `it` and `exit(` contains `xit`; without
# a word boundary the scanner minted a test unit whose name was the string
# literal that followed, and any diff of the file reported `"\n"` as a
# removed test at high severity. The file below touches no assertion.
_ISSUE_156 = (
    b'import test from "node:test";\n'
    b'test("only", (t) => {\n'
    b'  const a = "x\\ny".split("\\n").slice(-1).join("\\n");\n'
    b'  const b = "p\\nq".split("\\n").slice(-1).join("\\n");\n'
    b'  t.assert.ok(a && b);\n'
    b'});\n'
)


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


def test_string_literal_method_call_is_not_a_test_unit():
    parsed = parse_javascript(_ISSUE_156)
    assert [u.qualname for u in parsed.units] == ["only"]
    assert parsed.units[0].side.markers == []


def test_split_literal_diff_reports_no_test_disabled():
    after = _ISSUE_156 + b"\n// a comment\n"
    file = align_file(
        "t.test.mjs",
        "test",
        "modified",
        parse_javascript(_ISSUE_156),
        parse_javascript(after),
    )
    assert file.alignment == "full"
    assert [u.qualname for u in file.units if u.after is None] == []
    ir = IR(base="base", head="head", files=[file], globals=DiffGlobals())
    assert [f for f in detect(ir) if f.rule == "TEST_DISABLED"] == []


def test_identifier_before_bracket_words_still_not_matched():
    # `exit(` carries `xit`, `submit(` carries `it` — no unit from either.
    parsed = parse_javascript(
        b'test("real", () => {\n'
        b'  exit(1);\n'
        b'  submit("\\n");\n'
        b'  expect(x).toBe(1);\n'
        b'});\n'
    )
    assert [u.qualname for u in parsed.units] == ["real"]


def test_property_access_it_still_matches():
    # `.` is a non-word character, so `suite.it(...)` keeps working.
    parsed = parse_javascript(b'suite.it("nested", () => {});\n')
    assert [u.qualname for u in parsed.units] == ["nested"]
