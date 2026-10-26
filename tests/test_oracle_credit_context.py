"""Oracle relocation needs the same static obligations, never text/mass alone.

These source strings are parsed by CheckWash and are never executed.
"""
import datetime
import ast
import copy

import pytest

from checkwash.change import FileChange
from checkwash.allowlist import AllowEntry
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import Evidence, Finding
from checkwash.gating import apply_gates
from checkwash.ir.model import IR, to_jsonable
from checkwash.ir.model import UnitSide
from checkwash.oracle_credit import _dump, assertion_keys, valid_proof


TODAY = datetime.date(2026, 10, 27)
BASE = '''import pytest
from calc import calc
@pytest.mark.parametrize("x,expected", [(10,20), (20,40), (30,60)])
def test_calc(x, expected):
    assert calc(x) == expected
'''
A = '''from calc import calc
def test_checkout():
    x = 10
    expected = 999999
    assert calc(x) == expected
'''
B = '''import pytest
from calc import calc
@pytest.mark.parametrize("x,expected", [(0,0), (0,0), (0,0)])
def test_checkout_v2(x, expected):
    res = calc(x)
    assert res == 0
'''


def check(before, after, *, freeze=False, fail_on="high", move=False, path="tests/test_calc.py", snapshot=None):
    changes = [FileChange(path, "modified", before.encode(), after.encode())]
    if move:
        changes = [FileChange(path, "deleted", before.encode(), None),
                   FileChange(path.replace("test_calc", "test_moved"), "added", None, after.encode())]
    sources = {"calc.py": b"def calc(x):\n    return x * 2\n", **(snapshot or {})}
    return analyze(changes, Config(fail_on=fail_on), Contract(oracle_freeze=freeze), [], TODAY,
                   root_reader=sources.get, root_searcher=lambda _: [])


@pytest.mark.parametrize("after", [A, B])
@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("fail_on,verdict", [("warn", "block"), ("high", "block"), ("critical", "pass")])
def test_default_and_frozen_renamed_oracle_laundering_has_no_text_or_mass_credit(after, freeze, fail_on, verdict):
    _ir, findings, actual = check(BASE, after, freeze=freeze, fail_on=fail_on)
    disabled = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert disabled and all(f.severity == "high" for f in disabled)
    assert all(not set(f.deescalators) & {"ASSERTION_MOVED", "RESTRUCTURED", "SPLIT_OR_RENAMED"} for f in disabled)
    assert all(("ORACLE_FREEZE" in f.escalators) == freeze for f in disabled)
    assert actual == verdict


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("replacement", ["[(10,999), (20,40), (30,60)]", "[(0,0), (0,0), (0,0)]"])
def test_cross_file_decorator_change_cannot_borrow_identical_function_body(freeze, replacement):
    _ir, findings, verdict = check(BASE, BASE.replace("[(10,20), (20,40), (30,60)]", replacement),
                                   freeze=freeze, move=True)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("move", [False, True])
def test_pure_rename_or_move_preserves_the_original_literal_table(freeze, move):
    _ir, findings, verdict = check(BASE, BASE if move else BASE.replace("test_calc", "test_checkout"),
                                   freeze=freeze, move=move)
    assert verdict == "pass"
    assert not any(f.severity in {"high", "critical"} for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_preserved_literal_unroll_still_passes(freeze):
    after = '''from calc import calc
def test_checkout():
    assert calc(10) == 20
    assert calc(20) == 40
    assert calc(30) == 60
'''
    _ir, findings, verdict = check(BASE, after, freeze=freeze)
    assert verdict == "pass" and not findings


@pytest.mark.parametrize("freeze", [False, True])
def test_module_binding_change_during_move_is_not_equivalence(freeze):
    before = "from calc import calc\nEXPECTED = 20\ndef test_calc():\n    assert calc(10) == EXPECTED\n"
    after = before.replace("EXPECTED = 20", "EXPECTED = 999")
    _ir, findings, verdict = check(before, after, freeze=freeze, move=True)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_unknown_custom_decorator_is_not_an_oracle_proof(freeze):
    source = "from calc import calc\nfrom helpers import customize\n@customize\ndef test_calc():\n    assert calc(10) == 20\n"
    _ir, findings, verdict = check(source, source, freeze=freeze, move=True)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_direct_assert_removed_text_credit_without_context_remains_high(freeze):
    ir = IR("base", "head")
    ir.globals.moved_assertion_texts = ["assert calc(x) == expected"]
    finding = Finding("ASSERT_REMOVED", "warn", "removed", "tests/test_calc.py", "test_calc",
                      before=Evidence("assert calc(x) == expected", (0, 26)), fingerprint="synthetic")
    verdict = apply_gates(ir, [finding], Contract(oracle_freeze=freeze), Config(), [], TODAY)
    assert verdict == "block" and finding.severity == "high"
    assert "ASSERTION_MOVED" not in finding.deescalators
    assert ("ORACLE_FREEZE" in finding.escalators) == freeze


@pytest.mark.parametrize("extension", ["js", "ts"])
@pytest.mark.parametrize("freeze", [False, True])
def test_javascript_local_context_change_does_not_earn_relocation_credit(extension, freeze):
    before = 'test("total", () => { const expected = 75; expect(total()).toBe(expected); });\n'
    after = 'test("renamed", () => { const expected = 0; expect(total()).toBe(expected); });\n'
    _ir, findings, verdict = check(before, after, freeze=freeze, path=f"tests/value.test.{extension}")
    assert verdict == "block"
    assert any(f.rule == "EXPECTATION_DEFINITION_CHANGED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("extension", ["js", "ts"])
@pytest.mark.parametrize("freeze", [False, True])
def test_javascript_exact_live_relocation_is_preserved(extension, freeze):
    source = 'test("total", () => { expect(total()).toBe(75); });\n'
    before = f"tests/a.test.{extension}"
    changes = [FileChange(before, "deleted", source.encode(), None),
               FileChange(f"tests/b.test.{extension}", "added", None, source.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(oracle_freeze=freeze), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "pass"
    assert all(f.severity == "info" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_proved_text_only_refactor_still_obeys_freeze(freeze):
    before = "from calc import calc\ndef test_calc():\n    x = 10\n    assert calc(x) == 20\n"
    after = before.replace("def test_calc():\n", 'def test_checkout():\n    "Rewritten documentation."\n')
    _ir, findings, verdict = check(before, after, freeze=freeze, move=True)
    assert findings and all("ASSERTION_MOVED" in f.deescalators for f in findings)
    assert all(f.severity == ("high" if freeze else "info") for f in findings)
    assert verdict == ("block" if freeze else "pass")


def test_whole_unit_credit_cannot_be_reused_as_assertion_credit():
    before = "from calc import calc\ndef test_one():\n    assert calc(10) == 20\ndef test_two():\n    assert calc(10) == 20\n"
    after = "from calc import calc\ndef test_survivor():\n    assert calc(10) == 20\n"
    changes = [FileChange("tests/test_a.py", "deleted", before.encode(), None),
               FileChange("tests/test_b.py", "added", None, after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"
    assert sum(f.severity == "info" for f in findings if f.rule == "TEST_DISABLED") == 1
    assert sum(f.severity == "high" for f in findings if f.rule == "TEST_DISABLED") == 1


@pytest.mark.parametrize("changed", [False, True])
def test_unchanged_duplicate_needs_the_same_decorator_and_definitions(changed):
    survivor = BASE.replace("[(10,20), (20,40), (30,60)]", "[(0,0), (0,0), (0,0)]") if changed else BASE
    snapshot = {"tests/test_survivor.py": survivor.encode()}
    _ir, findings, verdict = analyze([FileChange("tests/test_calc.py", "deleted", BASE.encode(), None)],
        Config(), Contract(oracle_freeze=True), [], TODAY, root_reader=snapshot.get,
        root_searcher=lambda _: [], head_reader=snapshot.get,
        head_searcher=lambda _: ["tests/test_survivor.py"])
    disabled = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert disabled and all(("DUPLICATE_REMAINS" in f.deescalators) != changed for f in disabled)
    assert verdict == ("block" if changed else "pass")


def test_serialized_proof_ast_dump_ignores_only_synthetic_empty_type_params():
    original = ast.parse("def test_x():\n    assert 1 == 1\n")
    changed = copy.deepcopy(original)
    changed.body[0]._fields = (*changed.body[0]._fields, "type_params")
    changed.body[0].type_params = []
    assert _dump(changed) == _dump(original)
    changed.body[0].type_params = [ast.Name(id="T", ctx=ast.Load())]
    with pytest.raises(ValueError, match="generic syntax"):
        _dump(changed)


@pytest.mark.parametrize("malformed", [None, [], {"a0": None}, {"a0": "short"}, {1: "a" * 64}])
def test_optional_proof_metadata_is_typed_and_unknown_never_means_equivalent(malformed):
    side = UnitSide((0, 1))
    side.oracle_assertion_contexts = malformed
    assert assertion_keys(side) == []
    assert not valid_proof(malformed)


@pytest.mark.parametrize("value", ["../alpha", "../alpha?literal"])
def test_relative_expected_string_is_data_never_an_import_alias(value):
    before = 'const expected = "./alpha"; test("old", () => { expect(actual()).toBe(expected); });\n'
    after = f'const expected = "{value}"; test("new", () => {{ expect(actual()).toBe(expected); }});\n'
    changes = [FileChange("tests/a.test.js", "deleted", before.encode(), None),
               FileChange("tests/sub/b.test.js", "added", None, after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


def test_unchanged_relative_expected_data_is_preserved_across_directories():
    source = 'const expected = "./alpha"; test("old", () => { expect(actual()).toBe(expected); });\n'
    changes = [FileChange("tests/a.test.js", "deleted", source.encode(), None),
               FileChange("tests/sub/b.test.js", "added", None, source.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "pass"
    assert all(f.severity == "info" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_direct_assert_removed_proof_spends_credit_and_applies_e2(freeze):
    before = 'test("a", () => { expect(total()).toBe(75); expect(1).toBe(1); });\ntest("b", () => { expect(2).toBe(2); });\n'
    after = 'test("a", () => { expect(1).toBe(1); });\ntest("b", () => { expect(2).toBe(2); expect(total()).toBe(75); });\n'
    _ir, findings, verdict = check(before, after, freeze=freeze, path="tests/value.test.js")
    removed = [f for f in findings if f.rule == "ASSERT_REMOVED"]
    assert len(removed) == 1
    assert removed[0].severity == ("high" if freeze else "info")
    assert "ASSERTION_MOVED" in removed[0].deescalators
    assert ("ORACLE_FREEZE" in removed[0].escalators) == freeze
    assert verdict == ("block" if freeze else "pass")


@pytest.mark.parametrize("expired", [False, True])
def test_exact_valid_base_exemption_still_precedes_the_oracle_policy(expired):
    changes = [FileChange("tests/test_calc.py", "modified", BASE.encode(), A.encode())]
    kwargs = {"root_reader": lambda _: None, "root_searcher": lambda _: []}
    _ir, before, _verdict = analyze(changes, Config(), Contract(oracle_freeze=True), [], TODAY, **kwargs)
    key = next(f.fingerprint for f in before if f.rule == "TEST_DISABLED")
    entry = AllowEntry(key, "TEST_DISABLED", "exact previously reviewed context", "maintainer",
                       "2026-10-01", "2026-10-26" if expired else "2026-11-01")
    _ir, findings, verdict = analyze(changes, Config(), Contract(oracle_freeze=True), [entry], TODAY, **kwargs)
    disabled = next(f for f in findings if f.rule == "TEST_DISABLED")
    assert disabled.allowlisted != expired
    assert verdict == ("block" if expired else "pass")
    assert disabled.fingerprint == key


def test_proof_metadata_serializes_as_canonical_string_maps_and_crlf_is_inert():
    changes = [FileChange("tests/test_old.py", "deleted", BASE.replace("\n", "\r\n").encode(), None),
               FileChange("tests/test_new.py", "added", None, BASE.encode())]
    ir, _findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
        root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "pass"
    payload = to_jsonable(ir)
    sides = [unit[half] for file in payload["files"] for unit in file["units"]
             for half in ("before", "after") if unit[half] is not None]
    assert len({side["oracle_context"] for side in sides}) == 1
    assert all(valid_proof(side["oracle_context"]) and isinstance(side["oracle_assertion_contexts"], dict)
               and all(isinstance(name, str) and valid_proof(key) for name, key in side["oracle_assertion_contexts"].items())
               for side in sides)


def test_ordinary_string_containing_import_words_never_becomes_a_specifier():
    before = 'const expected = "from \'./alpha\'"; test("old", () => { expect(actual()).toBe(expected); });\n'
    after = before.replace("./alpha", "../alpha")
    changes = [FileChange("tests/a.test.js", "deleted", before.encode(), None),
               FileChange("tests/sub/b.test.js", "added", None, after.encode())]
    _ir, _findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"


@pytest.mark.parametrize("language", ["python", "javascript"])
def test_unknown_assertion_calls_cannot_be_reordered_into_new_units(language):
    if language == "python":
        before = "from subject import advance, current\ndef test_pair():\n    assert advance() == 1\n    assert current() == 1\n"
        after = "from subject import advance, current\ndef test_new_current():\n    assert current() == 1\ndef test_new_advance():\n    assert advance() == 1\n"
        path = "tests/test_state.py"
    else:
        before = 'import {advance,current} from "./subject";\ntest("old",()=>{expect(advance()).toBe(1);expect(current()).toBe(1)})\n'
        after = 'import {advance,current} from "./subject";\ntest("new1",()=>{expect(current()).toBe(1)})\ntest("new2",()=>{expect(advance()).toBe(1)})\n'
        path = "tests/a.test.js"
    _ir, findings, verdict = check(before, after, path=path)
    assert verdict == "block"
    assert any(f.rule in {"TEST_DISABLED", "ASSERT_REMOVED"} and f.severity == "high" for f in findings)


def test_aligned_removed_assertion_cannot_skip_unknown_prior_call():
    before = "from subject import advance, current\ndef test_pair():\n    assert advance() == 1\n    assert current() == 1\n"
    after = "from subject import advance, current\ndef test_pair():\n    assert advance() == 1\ndef test_current():\n    assert current() == 1\n"
    _ir, findings, verdict = check(before, after, path="tests/test_state.py")
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_second_rename_from_a_into_b_has_no_mass_credit(freeze):
    _ir, findings, verdict = check(A, B, freeze=freeze)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("mutation", ["builtins.getattr = fake", "alias.getattr = fake",
    'setattr(builtins, "getattr", fake)', 'builtins.__dict__["getattr"] = fake'])
def test_builtin_getattr_mutation_is_unknown_not_attribute_equivalence(mutation):
    setup = "import pytest\nimport builtins\nimport builtins as alias\nclass Subject:\n    value = 999\ndef fake(*args):\n    return 1\n"
    before = setup + '@pytest.mark.parametrize("unused", [0])\ndef test_before(unused):\n    subject = Subject()\n    ' + mutation + '\n    assert subject.value == 1\n'
    after = setup + 'def test_after():\n    subject = Subject()\n    ' + mutation + '\n    assert getattr(subject, "value") == 1\n'
    _ir, findings, verdict = check(before, after)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("declaration", ['import "./setup";', 'import /* comment */ "./setup";',
    'import "\\u002e/setup";', 'const path = "./setup"; import(/* comment */ path);'])
def test_bare_relative_side_effect_import_cannot_change_resolution_during_move(freeze, declaration):
    source = declaration + '\ntest("same", () => { expect(actual()).toBe(42); });\n'
    changes = [FileChange("tests/a.test.js", "deleted", source.encode(), None),
               FileChange("tests/sub/b.test.js", "added", None, source.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(oracle_freeze=freeze), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("different", [False, True])
def test_package_initializers_are_part_of_the_startup_proof(freeze, different):
    source = b"from common import CURRENT\ndef test_read():\n    assert CURRENT == 1\n"
    changes = [FileChange("tests/left/test_a.py", "deleted", source, None),
               FileChange("tests/right/test_b.py", "added", None, source)]
    snapshot = {"common.py": b"CURRENT = 1\n", "tests/__init__.py": b"",
        "tests/left/__init__.py": b"import common\ncommon.CURRENT = 999\n" if different else b"",
        "tests/right/__init__.py": b"import common\ncommon.CURRENT = 1\n" if different else b""}
    _ir, findings, verdict = analyze(changes, Config(), Contract(oracle_freeze=freeze), [], TODAY,
                                     root_reader=snapshot.get, root_searcher=lambda _: [])
    assert verdict == ("block" if different else "pass")
    assert all(f.severity == ("high" if different else "info") for f in findings)


def test_optional_context_proof_failure_preserves_ordinary_analysis(monkeypatch):
    import checkwash.oracle_credit as credit
    def unavailable(*_args):
        raise RecursionError("owned proof fault injection")
    monkeypatch.setattr(credit, "_python_context", unavailable)
    _ir, findings, verdict = check(BASE, A)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("helper", ["def identify():\n    return __name__\n",
    "def identify():\n    return __file__\n", "def identify(*, value=__name__):\n    return value\n"])
def test_helper_module_identity_is_unknown_for_full_unit_move(freeze, helper):
    source = (helper + "def test_oracle():\n    assert identify() == 'test_b'\n").encode()
    changes = [FileChange("tests/test_a.py", "deleted", source, None),
               FileChange("tests/test_b.py", "added", None, source)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(oracle_freeze=freeze), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("metadata", ["__filename", "__dirname", "import.meta.url"])
def test_javascript_helper_file_identity_is_unknown(metadata):
    source = ('function identify() { return ' + metadata + '; }\ntest("same", () => { expect(identify()).toBe("new"); });\n').encode()
    changes = [FileChange("tests/a.test.js", "deleted", source, None),
               FileChange("tests/b.test.js", "added", None, source)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                     root_reader=lambda _: None, root_searcher=lambda _: [])
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("freeze", [False, True])
def test_opaque_imported_bootstrap_cannot_authorize_getattr_equivalence(freeze):
    before = "import pytest\nfrom bootstrap import bootstrap\n@pytest.mark.parametrize('unused', [0])\ndef test_before(unused):\n    subject = bootstrap()\n    assert subject.value == 1\n"
    after = "import pytest\nfrom bootstrap import bootstrap\ndef test_after():\n    subject = bootstrap()\n    assert getattr(subject, 'value') == 1\n"
    bootstrap = b"import builtins\nclass Subject:\n    value = 999\ndef fake(*args):\n    return 1\ndef bootstrap():\n    builtins.getattr = fake\n    return Subject()\n"
    _ir, findings, verdict = check(before, after, freeze=freeze, snapshot={"bootstrap.py": bootstrap})
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" and "RESTRUCTURED" not in f.deescalators
               for f in findings)
