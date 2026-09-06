"""Issue 131: transparent __bool__ carriers need a closed scalar proof."""

import datetime
import os
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import EngineError, FileChange, analyze


PATH = "tests/test_normalize.py"
CLASS = b'''class Matches:
    def __init__(self, got, expected):
        self.got = got
        self.expected = expected

    def __bool__(self):
        return self.got == self.expected
'''
BEFORE = b'from app.normalize import normalize\n\n' + CLASS + b'\ndef test_normalize():\n    assert Matches(normalize(" Ab "), "ab")\n'
AFTER = b'''from app.normalize import normalize

def expected_value(s):
    return s.strip().lower()

def test_normalize():
    assert expected_value(normalize(" Ab ")) == "ab"
'''
PRODUCTION = b'def normalize(s):\n    return s\n'
SNAPSHOT = {"src/app/normalize.py": PRODUCTION}


def run(before=BEFORE, after=AFTER, *, snapshot=SNAPSHOT, strict=True, inventory=True, extra=()):
    complete = {**snapshot, PATH: after}
    return analyze(
        [FileChange(PATH, "modified", before, after), *extra],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
        root_reader=complete.get if strict else None, head_reader=complete.get,
        root_searcher=(lambda needles: [p for p, b in sorted(complete.items())
                        if p.endswith(".py") and b and any(n.encode() in b for n in needles)]) if inventory else None,
    )


def old_assertion(ir):
    file = next(f for f in ir.files if f.path == PATH)
    return next(u for u in file.units if u.qualname == "test_normalize").before.assertions[0]


def test_reported_truthiness_to_normalized_equality_now_blocks():
    ir, findings, verdict = run()
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("SUBJECT_NORMALIZED", "high")]
    assertion = old_assertion(ir)
    assert assertion.form == "compare_eq"
    assert assertion.left == 'normalize(" Ab ")'
    assert assertion.right_value == "'ab'"
    assert not assertion.inherited


def test_real_pytest_confirms_unchanged_bug_is_hidden_by_the_rewrite(tmp_path):
    # Run only the fixed issue regression declared above, never repository code
    # supplied to the analyzer. Separate directories prevent stale pyc reuse.
    results = []
    for side, source in (("before", BEFORE), ("after", AFTER)):
        root = tmp_path / side
        (root / "src/app").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "src/app/normalize.py").write_bytes(PRODUCTION)
        (root / PATH).write_bytes(source)
        env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONUTF8": "1"}
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", PATH], cwd=root,
                                env=env, capture_output=True, text=True, timeout=30)
        results.append(result.returncode)
    assert results == [1, 0]
    assert run()[2] == "block"


def test_equivalent_inlining_and_extraction_keep_the_scalar_equality():
    inline = b'from app.normalize import normalize\n\ndef test_normalize():\n    assert normalize(" Ab ") == "ab"\n'
    for before, after in ((BEFORE, inline), (inline, BEFORE)):
        _, findings, verdict = run(before, after)
        assert verdict == "pass"
        assert findings == []


@pytest.mark.parametrize("literal", [b"1", b"True", b"None", b"'abc'"])
def test_exact_builtin_scalars_have_boolean_equality(literal):
    before = BEFORE.replace(b'" Ab "', literal).replace(b'"ab"', literal)
    inline = b'from app.normalize import normalize\n\ndef test_normalize():\n    assert normalize(' + literal + b') == ' + literal + b'\n'
    ir, findings, verdict = run(before, inline)
    assert old_assertion(ir).form == "compare_eq"
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("carrier", [
    CLASS.replace(b"class Matches:", b"class Matches(Base):"),
    CLASS.replace(b"class Matches:", b"class Matches(metaclass=Meta):"),
    CLASS.replace(b"class Matches:", b"@decorate\nclass Matches:"),
    CLASS.replace(b"    def __init__", b"    flag = True\n    def __init__"),
    CLASS + b"    def __new__(cls, *args):\n        return other\n",
    CLASS + b"    def __getattribute__(self, name):\n        return True\n",
    CLASS + b"    def __getattr__(self, name):\n        return True\n",
    CLASS + b"    def __setattr__(self, name, value):\n        pass\n",
    CLASS.replace(b"got, expected", b"got, expected=side_effect()"),
    CLASS.replace(b"got, expected", b"got: side_effect(), expected"),
    CLASS.replace(b"    def __bool__", b"    @decorate\n    def __bool__"),
    CLASS.replace(b"self.got = got", b"self.got = expected"),
    CLASS.replace(b"self.got = got", b"self.got = got.lower()"),
    CLASS.replace(b"        self.expected = expected\n", b""),
    CLASS.replace(b"self.got", b"self.__class__"),
    CLASS.replace(b"self.got", b"self.__dict__"),
    CLASS.replace(b"return self.got == self.expected", b"return self.got == self.expected if enabled else True"),
    CLASS.replace(b"return self.got == self.expected", b"return self.got != self.expected"),
    CLASS.replace(b"return self.got == self.expected", b"return self.got == self.got"),
    CLASS.replace(b"return self.got == self.expected", b"mutate()\n        return self.got == self.expected"),
])
def test_dynamic_or_incomplete_carriers_do_not_gain_synthetic_equality(carrier):
    ir, _, _ = run(BEFORE.replace(CLASS, carrier))
    assert old_assertion(ir).form == "truthy"


@pytest.mark.parametrize("extra", [
    b"\nMatches = other\n",
    b"\nMatches.__bool__ = lambda self: True\n",
    b"\nnormalize = lambda value: value\n",
    b"\nnormalize.__code__ = other.__code__\n",
    b"\ndef test_mutate():\n    assert setattr(Matches, '__bool__', lambda self: True) is None\n",
    b"\ndef test_mutate():\n    assert normalize(mutate()) == 'ab'\n",
])
def test_test_module_effects_and_rebindings_decline_projection(extra):
    ir, _, _ = run(BEFORE + extra)
    assert old_assertion(ir).form == "truthy"


@pytest.mark.parametrize("call", [
    b'Matches(normalize(" Ab "), expected="ab")',
    b'Matches(normalize(" Ab "), expected)',
    b'Matches(normalize(value()), "ab")',
    b'Matches(normalize(" Ab "), str("ab"))',
    b'Matches("ab", normalize(" Ab "))',
])
def test_nonliteral_forwarding_or_swapped_call_arguments_decline_projection(call):
    ir, _, _ = run(BEFORE.replace(b'Matches(normalize(" Ab "), "ab")', call))
    assert old_assertion(ir).form == "truthy"


@pytest.mark.parametrize("production", [
    b'def normalize(s):\n    return custom(s)\n',
    b'def normalize(s):\n    return s if condition else other\n',
    b'def normalize(s):\n    return [s]\n',
    b'class Scalar(str):\n    def __eq__(self, other):\n        return []\ndef normalize(s):\n    return Scalar(s)\n',
    b'def normalize(s):\n    mutate()\n    return s\n',
    b'@decorate\ndef normalize(s):\n    return s\n',
    b'def normalize(s=mutate()):\n    return s\n',
    PRODUCTION + b'\nnormalize = other\n',
])
def test_unknown_or_custom_equality_return_values_decline_projection(production):
    ir, _, _ = run(snapshot={"src/app/normalize.py": production})
    assert old_assertion(ir).form == "truthy"


@pytest.mark.parametrize("path, source", [
    ("app/normalize.py", PRODUCTION),
    ("tests/app/normalize.py", PRODUCTION),
    ("src/app/normalize/__init__.py", PRODUCTION),
    ("src/app/__init__.py", b"from . import normalize\nnormalize.normalize = lambda s: s\n"),
    ("tests/__init__.py", b"from app import normalize\nnormalize.normalize = lambda s: s\n"),
    ("tests/conftest.py", b"def pytest_configure(config):\n    patch()\n"),
    ("other/conftest.py", b"def pytest_configure(config):\n    patch()\n"),
    ("other/__init__.py", b"patch()\n"),
    ("other/test_sibling.py", b"from app import normalize\nnormalize.normalize = lambda s: s\n"),
    ("other/test_sibling.py", b"def test_mutate():\n    patch()\n"),
])
def test_ambiguous_or_executable_repository_startup_declines_projection(path, source):
    # A sibling collected module makes its package startup relevant too.
    ir, _, _ = run(snapshot={**SNAPSHOT, "other/test_sibling.py": b"def test_other():\n    pass\n", path: source})
    assert old_assertion(ir).form == "truthy"


@pytest.mark.parametrize("strict,inventory", [(False, True), (True, False), (False, False)])
def test_missing_strict_snapshot_or_inventory_declines_projection(strict, inventory):
    ir, _, _ = run(strict=strict, inventory=inventory)
    assert old_assertion(ir).form == "truthy"


def test_over_budget_inventory_and_unicode_scalar_decline_projection():
    extra_sources = {f"other/test_{i}.py": b"# source\n" for i in range(64)}
    ir, _, _ = run(snapshot={**SNAPSHOT, **extra_sources})
    assert old_assertion(ir).form == "truthy"
    ir, _, _ = run(BEFORE.replace(b'" Ab "', '"Straße"'.encode()))
    assert old_assertion(ir).form == "truthy"


def test_reader_errors_propagate_but_inventory_errors_withhold_projection():
    def unavailable(path):
        raise EngineError("snapshot unavailable")

    change = FileChange(PATH, "modified", BEFORE, AFTER)
    with pytest.raises(EngineError, match="snapshot unavailable"):
        analyze([change], Config(), Contract(), [], datetime.date(2026, 9, 6),
                root_reader=unavailable, root_searcher=lambda _: [PATH])
    ir, _, _ = analyze([change], Config(), Contract(), [], datetime.date(2026, 9, 6),
                       root_reader=SNAPSHOT.get, root_searcher=unavailable)
    assert old_assertion(ir).form == "truthy"


def test_other_changed_file_cannot_supply_current_side_only_scalar_proof():
    ir, _, _ = run(extra=[FileChange("src/app/normalize.py", "modified", b'def normalize(s):\n    return custom(s)\n', PRODUCTION)])
    assert old_assertion(ir).form == "truthy"


def test_projection_sides_are_independent_when_the_carrier_is_mutated():
    after = BEFORE.replace(b"return self.got == self.expected", b"return True")
    ir, _, verdict = run(after=after)
    assert old_assertion(ir).form == "compare_eq"
    unit = next(u for u in ir.files[0].units if u.qualname == "test_normalize")
    assert unit.after.assertions[0].form == "truthy"
    assert verdict == "block"


def test_original_native_assert_span_survives_unicode_comment_and_crlf():
    before = '# 原始比較\r\n'.encode() + BEFORE.replace(b"\n", b"\r\n")
    after = '# 原始比較\r\n'.encode() + AFTER.replace(b"\n", b"\r\n")
    ir, findings, verdict = run(before, after)
    assert verdict == "block"
    assertion = old_assertion(ir)
    source = before.decode().replace("\r\n", "\n")
    assert source[slice(*assertion.span)] == 'assert Matches(normalize(" Ab "), "ab")'
    assert findings[0].before.text == 'assert Matches(normalize(" Ab "), "ab")'
