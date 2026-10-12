"""Imported helper guards retain their module scope and cross-file evidence (#357)."""
import ast

import pytest

from checkwash.frontends.python.frontend import _Offsets
from checkwash.frontends.python.helper_skips import HelperGuard, HelperModule
from test_issue272_imported_helper_skips import APP, BASE, disabled, markers, module, outcome


def source(guard, prelude="", params="", body=""):
    return ("import os\nimport sys\nimport pytest\n" + prelude
            + f"\ndef gate({params}):\n" + body
            + f"    if {guard}:\n        pytest.skip('off')\n")


def run(text, *, call="gate()", defs="", path="tests/helpers.py"):
    imports = "from " + path[:-3].replace("/", ".") + " import gate"
    before = BASE if not defs else module("pass", imports="", defs=defs)
    after = module(call, imports, defs)
    snapshot = {**APP, "tests/__init__.py": b"", path: text.encode()}
    return outcome(before, after, snapshot=snapshot)


def guard(text, name="gate", path="tests/helpers.py"):
    helper, effect, evidence, conditions = single_outcome(text, name, path)
    return conditions[0] if conditions else None


def single_outcome(text, name="gate", path="tests/helpers.py"):
    outcomes = HelperModule(text.encode(), path).outcomes(name)
    assert len(outcomes) == 1
    return outcomes[0]


@pytest.mark.parametrize("replacement", [
    "if SWITCH:\n    WIN = os.environ.get('NET')\n",
    "WIN |= True\n",
    "del WIN\n",
    "def WIN():\n    return os.environ.get('NET')\n",
    "class WIN:\n    pass\n",
    "WIN, other = (os.environ.get('NET'), 1)\n",
    "for WIN in values:\n    pass\n",
    "with resource() as WIN:\n    pass\n",
])
def test_module_rebinding_does_not_reuse_stale_compatibility_constant(replacement):
    text = source("WIN", "WIN = sys.platform == 'win32'\n" + replacement)
    assert guard(text) == "helper.WIN"
    assert run(text) == ("block", [disabled("helper.gate.skip")])


@pytest.mark.parametrize("expression, prelude, closed", [
    ("not os.environ.get('NET')", "", "not os.environ.get('NET')"),
    ("WIN", "WIN = sys.platform == 'win32'\n", "(sys.platform == 'win32')"),
    ("OFF", "WIN = sys.platform == 'win32'\nOFF = not WIN\n", "(not (sys.platform == 'win32'))"),
    ("NET", "from config import NET\n", "helper.NET"),
    ("NET", "NET = True\nfrom config import NET\n", "helper.NET"),
    ("UNKNOWN", "", "helper.UNKNOWN"),
    ("A", "A = B\nB = A\n", "((helper.A))"),
    ("PLAT.startswith('win')", "PLAT = sys.platform\n", "(sys.platform).startswith('win')"),
])
def test_helper_module_closes_value_reads(expression, prelude, closed):
    assert guard(source(expression, prelude)) == closed


@pytest.mark.parametrize("expression, prelude, severity, verdict", [
    ("not NET", "NET = os.environ.get('NET')\n", "high", "block"),
    ("sys.platform == 'win32'", "", "warn", "pass"),
    ("WIN", "WIN = sys.platform == 'win32'\n", "warn", "pass"),
    ("sys.version_info < (3, 12)", "", "warn", "pass"),
    ("platform == 'win32'", "from sys import platform\n", "high", "block"),
])
def test_environment_blocks_and_compatibility_holds(expression, prelude, severity, verdict):
    assert run(source(expression, prelude)) == (verdict, [disabled("helper.gate.skip", severity)])


def test_test_constants_do_not_replace_a_helper_constant():
    text = source("NET", "NET = os.environ.get('NET')\n")
    assert run(text, defs="NET = sys.platform == 'win32'\n\n") == (
        "block", [disabled("helper.gate.skip")])


@pytest.mark.parametrize("params, body", [
    ("WIN", ""),
    ("", "    WIN = os.environ.get('NET')\n"),
    ("value", "    match value:\n        case {**WIN}:\n            pass\n"),
])
def test_helper_locals_are_not_module_constants(params, body):
    assert guard(source("WIN", "WIN = sys.platform == 'win32'\n", params, body)) == "helper.WIN"


@pytest.mark.parametrize("outer_params, inner_params, assignment", [
    ("", "WIN", ""),
    ("WIN", "", ""),
    ("", "", "    WIN = os.environ.get('NET')\n"),
])
def test_nested_helpers_keep_their_own_and_enclosing_locals(outer_params, inner_params, assignment):
    text = ("import pytest\nimport sys\nWIN = sys.platform == 'win32'\n"
            + f"def gate({outer_params}):\n" + assignment
            + f"    def inner({inner_params}):\n"
            + "        if WIN:\n            pytest.skip('off')\n    inner()\n")
    assert guard(text) == "helper.WIN"


def test_nested_helper_without_a_shadow_keeps_module_constant():
    text = ("import pytest\nimport sys\nWIN = sys.platform == 'win32'\n"
            "def gate():\n    def inner():\n        if WIN:\n"
            "            pytest.skip('off')\n    inner()\n")
    assert guard(text) == "(sys.platform == 'win32')"


def test_unknown_prefix_carries_no_module_path_tokens():
    text = source("UNKNOWN")
    path = "tests/platform/helpers.py"
    assert guard(text, path=path) == "helper.UNKNOWN"
    assert run(text, path=path) == ("block", [disabled("helper.gate.skip")])


def test_call_site_and_helper_conditions_are_conjoined():
    text = source("not NET", "NET = os.environ.get('NET')\n")
    helper = HelperModule(text.encode(), "tests/helpers.py")
    after = module("if sys.platform == 'win32':\n        gate()", "from tests.helpers import gate")
    actual = markers(after, lambda _module, name: helper.outcomes(name))
    assert actual == [("helper.gate.skip", "pytest.skip('off')",
                       "sys.platform == 'win32' and not (os.environ.get('NET'))")]


def test_intermediate_helper_conditions_are_retained():
    text = ("import pytest\nimport sys\n"
            "def gate():\n    if sys.platform == 'win32':\n        inner()\n"
            "def inner():\n    if UNKNOWN:\n        pytest.skip('off')\n")
    _name, _effect, _evidence, conditions = single_outcome(text)
    assert conditions == ("sys.platform == 'win32'", "helper.UNKNOWN")


def test_optional_import_handler_keeps_dependency_guard():
    text = ("import pytest\ndef gate():\n    try:\n        import optional_dep\n"
            "    except ImportError:\n        pytest.skip('off')\n")
    assert guard(text) == 'find_spec("optional_dep") is None'
    # D6's dependency-only hold is for suite controls. Individual helper
    # skips still require an interpreter/OS token; #357 does not widen D6.
    assert run(text) == ("block", [disabled("helper.gate.skip")])


def test_existing_guarded_call_is_no_new_event():
    text = source("not os.environ.get('NET')")
    before = module("gate()", "from tests.helpers import gate")
    snapshot = {**APP, "tests/helpers.py": text.encode(), "tests/__init__.py": b""}
    assert outcome(before, before + "\n", snapshot=snapshot) == ("pass", [])


def test_foreign_evidence_keeps_helper_file_unicode_offsets():
    text = source("not UNKNOWN", "LABEL = '測試'\n")
    _name, _effect, evidence, conditions = single_outcome(text)
    assert evidence.path == "tests/helpers.py"
    assert text[slice(*evidence.span)] == evidence.text == "pytest.skip('off')"
    assert conditions == ("not helper.UNKNOWN",)


def test_long_guard_stays_unknown_without_copying_source():
    text = source(" or ".join("UNKNOWN" for _ in range(1500)))
    tree = ast.parse(text)
    offsets = _Offsets(text)
    reads = []

    def text_of(node):
        reads.append(node)
        return offsets.seg(node)

    closer = HelperGuard(tree, text_of, offsets.span)
    condition = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If))
    assert closer(condition) == "helper.<unreadable>"
    assert reads == []
    assert run(text) == ("block", [disabled("helper.gate.skip")])


def test_closure_budget_is_shared_within_the_helper_module():
    text = source(" or ".join("FLAG" for _ in range(180)), "FLAG = '" + "x" * 200 + "'\n")
    tree = ast.parse(text)
    offsets = _Offsets(text)
    closer = HelperGuard(tree, offsets.seg, offsets.span)
    condition = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If))
    for _ in range(100):
        assert len(closer(condition)) <= 4096
    assert closer(condition) == "helper.<unreadable>"
