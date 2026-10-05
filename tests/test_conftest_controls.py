"""Every marker name the Python frontend can mint has a kind (#199 Q4).

`conftest_controls` is the one classification that the collection inventory
and TEST_DISABLED read. A name it does not know joins no reader, so a new
family has to be classified there before either reader acts on it. These
tests keep that true:

- every place the Python frontend mints a marker name is listed in `SITES`.
  A new place, or a new family at a known place, fails
  `test_every_minting_site_is_listed` until it is listed here and
  classified in `conftest_controls`;
- every family listed has the kind it is meant to have, and the kinds keep
  TEST_DISABLED's `shape` exactly as it was;
- every marker the frontend mints over the fixture corpus has a kind.
"""
import ast
import pathlib

import pytest

from checkwash.cases import parse_case
from checkwash.frontends.python import conftest_controls as cc
from checkwash.frontends.python.frontend import _CONFTEST_HOOKS, _SKIP_CALLS, _SKIP_DECORATORS, parse_python
from checkwash.frontends.python.runtime_controls import _HOOKS as RUNTIME_HOOKS

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "src" / "checkwash" / "frontends" / "python"
CASES = sorted((ROOT / "tests" / "cases").glob("*.gwcase"))


def _head(node):
    """The literal start that every name this expression builds shares."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else repr(node.value)
    if isinstance(node, ast.JoinedStr):
        head = ""
        for part in node.values:
            if not (isinstance(part, ast.Constant) and isinstance(part.value, str)):
                return head + "{}"
            head += part.value
        return head
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(_head(node.left), str):
        return _head(node.left) + "{}"
    if isinstance(node, ast.Call):
        return "call " + ast.unparse(node.func)
    if isinstance(node, ast.Name):
        return "name " + node.id
    return "expr " + ast.unparse(node)


def _own(func):
    """The nodes of a function body, without those of functions nested in it."""
    stack = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _scan():
    """(module, function, head) for every marker name the Python frontend mints.

    A `Marker(name=...)` call is a site. A name variable is followed to its
    assignments and to the generator it is read from, and a generator to what
    it yields, including what it yields from another generator.
    """
    functions = {}
    for path in sorted(FRONTEND.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault(node.name, (path.stem, node))
    sites, generators, pending = [], set(), []

    def follow(module, func, variables):
        for node in _own(func):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in variables:
                        value = node.value.elts[0] if isinstance(node.value, ast.Tuple) else node.value
                        sites.append((module, func.name, f"{target.id} = {_head(value)}"))
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
                first = node.target.elts[0]
                if isinstance(first, ast.Name) and first.id in variables and isinstance(node.iter, ast.Call):
                    callee = ast.unparse(node.iter.func)
                    sites.append((module, func.name, f"{first.id} in {callee}"))
                    pending.append(callee)

    for module, func in functions.values():
        variables = set()
        for node in _own(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Marker":
                arg = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
                sites.append((module, func.name, _head(arg)))
                if isinstance(arg, ast.Name):
                    variables.add(arg.id)
        follow(module, func, variables)
    while pending:
        name = pending.pop()
        if name in generators or name not in functions:
            continue
        generators.add(name)
        module, func = functions[name]
        variables = set()
        for node in _own(func):
            if isinstance(node, ast.Yield) and node.value is not None:
                first = node.value.elts[0] if isinstance(node.value, ast.Tuple) else node.value
                sites.append((module, name, _head(first)))
                if isinstance(first, ast.Name):
                    variables.add(first.id)
            elif isinstance(node, ast.YieldFrom) and isinstance(node.value, ast.Call):
                callee = ast.unparse(node.value.func)
                sites.append((module, name, f"from {callee}"))
                pending.append(callee)
        follow(module, func, variables)
    return sorted(sites)


# Where the Python frontend mints marker names. A head that is a literal (or
# the literal start of an f-string) is a family; the rest is plumbing that
# carries a name from where it is built to a `Marker`.
SITES = sorted([
    ("frontend", "_collect_unit", "name = call _dotted"),
    ("frontend", "_collect_unit", "name name"),
    ("frontend", "_conftest_unit", "conftest.collect_ignore"),
    ("frontend", "_conftest_unit", "name = None"),
    ("frontend", "_conftest_unit", "name = conftest.add_marker_skip"),
    ("frontend", "_conftest_unit", "name = conftest.{}"),
    ("frontend", "_conftest_unit", "name in runtime_controls"),
    ("frontend", "_conftest_unit", "name name"),
    ("frontend", "_conftest_unit", "name name"),
    ("frontend", "_decorator_markers", "call _marker_identity"),
    ("frontend", "_module_skip_markers", "module.__test__"),
    ("frontend", "_module_skip_markers", "module.{}"),
    ("frontend", "_pytestmark_markers", "call _marker_identity"),
    ("frontend", "setup_markers", "setup.{}"),
    ("runtime_controls", "runtime_controls", "conftest.runtime.{}"),
    ("runtime_controls", "runtime_controls", "from fixture_setup_controls"),
    ("runtime_controls", "runtime_controls", "from setup_skip_controls"),
    ("setup_skip_controls", "fixture_setup_controls", "conftest.runtime.fixture.{}"),
    ("setup_skip_controls", "setup_skip_controls", "name result"),
    ("setup_skip_controls", "setup_skip_controls", "result = None"),
    ("setup_skip_controls", "setup_skip_controls", "result = conftest.runtime.pytest_runtest_setup.{}"),
])

PLUMBING = {"name name", "name result", "name = None", "result = None", "name in runtime_controls",
            "from fixture_setup_controls", "from setup_skip_controls"}

# Each family, the kind it has, and names it mints.
FAMILIES = {
    "call _marker_identity": (cc.SKIP_MARK, sorted(_SKIP_DECORATORS) + ["pytest.mark.skipif(sys.platform == 'win32')",
                                                                         "pytest.mark.xfail(reason='flaky')"]),
    "module.__test__": (cc.MODULE, ["module.__test__"]),
    "module.{}": (cc.MODULE, ["module.skip", "module.xfail", "module.importorskip"]),
    # `_collect_unit` mints a called name only when it is in `_SKIP_CALLS`.
    "name = call _dotted": (cc.SKIP_CALL, sorted(_SKIP_CALLS)),
    "conftest.collect_ignore": (cc.COLLECTION, ["conftest.collect_ignore"]),
    "name = conftest.{}": (cc.COLLECTION, [f"conftest.{hook}" for hook in sorted(_CONFTEST_HOOKS)]),
    "name = conftest.add_marker_skip": (cc.COLLECTION, ["conftest.add_marker_skip"]),
    "setup.{}": (cc.SETUP, ["setup.needs_network.skip", "setup.setup_method.xfail"]),
    "conftest.runtime.{}": (cc.RUNTIME, [f"conftest.runtime.{hook}.report-passed.e3b0c44298fc1c14"
                                         for hook in sorted(RUNTIME_HOOKS)]),
    "result = conftest.runtime.pytest_runtest_setup.{}": (cc.RUNTIME, ["conftest.runtime.pytest_runtest_setup.skip",
                                                                       "conftest.runtime.pytest_runtest_setup.xfail"]),
    "conftest.runtime.fixture.{}": (cc.FIXTURE_SETUP, ["conftest.runtime.fixture.needs_network.skip",
                                                       "conftest.runtime.fixture.needs_network.xfail"]),
}

JS_NAMES = ["test.skip", "test.skipIf(process.env.CI)", "test.fails", "test.unfocused"]


def test_every_minting_site_is_listed():
    assert _scan() == SITES, (
        "the Python frontend mints a marker name somewhere this test does not list: classify the "
        "family in frontends/python/conftest_controls.py, then list the site in SITES and FAMILIES")


def test_every_listed_family_has_its_kind():
    assert {head for _, _, head in SITES} - PLUMBING == set(FAMILIES)
    for head, (kind, names) in FAMILIES.items():
        assert names
        assert {name: cc.marker_kind(name) for name in names} == {name: kind for name in names}, head


def test_kinds_keep_the_test_disabled_shape():
    """TEST_DISABLED's `collection_control` shape was every `conftest.` name (#199 Q4)."""
    for _kind, names in FAMILIES.values():
        for name in names:
            assert (cc.marker_kind(name) in cc.SUITE_KINDS) == name.startswith("conftest."), name


def test_collection_controls_are_the_spec_list():
    """SPEC §2b's collection controls (#199 Q1). A conftest's `pytestmark` is not one (#209 Q3)."""
    controls = {name for kind, names in FAMILIES.values() for name in names if cc.is_collection_control(name)}
    expected = {name for kind, names in FAMILIES.values() if kind == cc.COLLECTION for name in names}
    assert controls == expected
    assert controls >= {"conftest.collect_ignore", "conftest.pytest_ignore_collect",
                        "conftest.pytest_collection_modifyitems", "conftest.add_marker_skip"}


@pytest.mark.parametrize("name", ["conftest.something_new", "conftest", "fixture.needs_network.skip", "", *JS_NAMES])
def test_a_name_without_a_family_joins_no_reader(name):
    assert cc.marker_kind(name) is None
    assert not cc.is_collection_control(name)


def test_the_readers_classify_through_this_module():
    for reader in ("collection_inventory.py", "detectors/test_disabled.py"):
        text = (ROOT / "src" / "checkwash" / reader).read_text(encoding="utf-8")
        assert "conftest_controls" in text, reader
        assert 'startswith("conftest.' not in text and 'startswith("setup.' not in text, reader


def _sources(case):
    for files in (case.before, case.after, case.head):
        for path, text in files.items():
            if path.endswith(".py"):
                yield path, text.encode("utf-8")


def test_every_marker_minted_over_the_fixture_corpus_has_a_kind():
    minted = set()
    for case_path in CASES:
        for path, data in _sources(parse_case(case_path.read_text(encoding="utf-8"))):
            parsed = parse_python(data, collect_tests=True, conftest=path.rsplit("/", 1)[-1] == "conftest.py")
            minted |= {m.name for unit in parsed.units for m in unit.side.markers}
    assert minted
    assert sorted(name for name in minted if cc.marker_kind(name) is None) == []
