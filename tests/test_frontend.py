"""Frontend unit tests: strength classification, markers, parse failure."""

from greenwash.frontends.python.frontend import parse_python
from greenwash.ir import strength as S


def _single_test_assertions(src: str):
    parsed = parse_python(src.encode(), collect_tests=True)
    assert parsed.parse_ok
    assert len(parsed.units) == 1
    return parsed.units[0].side.assertions


def _strength_of(line: str) -> int | None:
    src = f"def test_x():\n    {line}\n"
    asserts = _single_test_assertions(src)
    assert len(asserts) == 1, f"expected 1 assertion for {line!r}"
    return asserts[0].strength


def test_lattice_classification():
    assert _strength_of("assert total == 105.3") == S.EXACT_VALUE
    assert _strength_of("assert total != 0") == S.EXACT_VALUE
    assert _strength_of("assert total > 0") == S.BOUND
    assert _strength_of("assert 'x' in body") == S.PATTERN
    assert _strength_of("assert value is not None") == S.NON_NULL
    assert _strength_of("assert flag") == S.TRUTHY
    assert _strength_of("assert True") == S.TAUTOLOGY
    assert _strength_of("assert 1 == 1") == S.TAUTOLOGY
    assert _strength_of("assert len(items) == 3") == S.TYPE_SHAPE
    assert _strength_of("assert isinstance(x, dict)") == S.TYPE_SHAPE


def test_approx_epsilon_extracted():
    asserts = _single_test_assertions(
        "import pytest\n\ndef test_x():\n    assert total == pytest.approx(105.3, rel=1e-6)\n"
    )
    assert asserts[0].strength == S.APPROX
    assert asserts[0].epsilon == "1e-6"


def test_unittest_mapping():
    src = (
        "class TestX:\n"
        "    def test_a(self):\n"
        "        self.assertEqual(f(), 42)\n"
        "        self.assertTrue(f())\n"
        "        self.assertIsNotNone(f())\n"
    )
    asserts = _single_test_assertions(src)
    assert [a.strength for a in asserts] == [S.EXACT_VALUE, S.TRUTHY, S.NON_NULL]


def test_unknown_helper_is_unclassified():
    asserts = _single_test_assertions(
        "def test_x():\n    self.assertRaises(ValueError, f)\n"
    )
    assert asserts[0].strength is None  # fail-safe: no guess


def test_skip_markers_detected():
    src = (
        "import pytest\n\n"
        "@pytest.mark.skip(reason='later')\n"
        "def test_x():\n"
        "    assert f() == 1\n"
    )
    parsed = parse_python(src.encode(), collect_tests=True)
    assert [m.name for m in parsed.units[0].side.markers] == ["pytest.mark.skip"]


def test_syntax_error_is_visible_degradation():
    parsed = parse_python(b"def broken(:\n    pass\n", collect_tests=True)
    assert parsed.parse_ok is False


def test_bom_stripped():
    # Windows tooling (e.g. PowerShell 5.1 Set-Content -Encoding utf8)
    # prepends a BOM; it must not break parsing.
    bom = b"\xef\xbb\xbfdef test_x():\n    assert f() == 1\n"
    parsed = parse_python(bom, collect_tests=True)
    assert parsed.parse_ok
    assert len(parsed.units) == 1


def test_crlf_normalized():
    lf = parse_python(b"def test_x():\n    assert f() == 1\n", collect_tests=True)
    crlf = parse_python(b"def test_x():\r\n    assert f() == 1\r\n", collect_tests=True)
    a, b = lf.units[0].side.assertions[0], crlf.units[0].side.assertions[0]
    assert a.text == b.text
    assert a.span == b.span


def test_docstring_and_comment_changes_are_trivial():
    before = parse_python(b"def f(x):\n    return x + 1\n", collect_tests=False)
    after = parse_python(
        b"# improved robustness\ndef f(x):\n    \"\"\"Add one.\"\"\"\n    return x + 1\n",
        collect_tests=False,
    )
    assert before.module_fingerprint == after.module_fingerprint
    assert before.symbols["f"] == after.symbols["f"]


def test_behaviour_change_is_nontrivial():
    before = parse_python(b"def f(x):\n    return x + 1\n", collect_tests=False)
    after = parse_python(b"def f(x):\n    return x + 2\n", collect_tests=False)
    assert before.module_fingerprint != after.module_fingerprint
    assert before.symbols["f"] != after.symbols["f"]


def test_suppression_scan():
    parsed = parse_python(
        b"import os  # noqa\nx = 1  # type: ignore\n", collect_tests=False
    )
    assert len(parsed.suppressions) == 2
