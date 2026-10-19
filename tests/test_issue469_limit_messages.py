"""Issue #469: the subject-replacement node limit and the stand-in step limits.

Ruling 469 (owner, 2026-10-18). The subject-replacement pass reads the
stand-in pass's 200,000-node limit, so a test file over the old 30,000 nodes
gives a verdict; its node and byte refusals name the path, the requested side
and the counts. The stand-in step limits stay, and their refusal names which
counter fired, the file, the side, the unit and that counter's steps and
limit. The pass reads each side's module statements once per file (the
owner's choice of 2026-10-19), and keeps the module reads of the
assertion-helper, changed-callee and literal-helper proofs too (the owner's
second choice of that day), and the answers of the `math.gcd` import
authority and the parameterized-helper checks once per file (the owner's
third choice of that day); the last pins show that none of them changes a
result. Source bytes are parsed only; the sources here are never executed.
"""

import ast
import datetime

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.conftest_context import ConftestContext
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import literal_stdlib_standins as literal_stdlib
from checkwash.frontends.python import replacement_authority
from checkwash.frontends.python import standin_installations as standin
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python import subject_replacements as subject
from checkwash.ir.markers import parse_expr
from checkwash.ir.model import IR, DiffGlobals

from test_mock_testcase_replacements import AFTER as TESTCASE_AFTER, BEFORE as TESTCASE_BEFORE
from test_standin_installations_main import judge as judge_installations

NODE_REFUSAL = "subject replacement source exceeds the syntax node limit: "
BYTE_REFUSAL = "subject replacement source exceeds the byte limit: "
STEP_REFUSAL = "stand-in execution proof exceeds the source step limit: "
SHARED = "; the unit is where the shared analysis budget ran out, not necessarily its cause"

PATH = "tests/test_billing.py"
PRODUCTION = {"app/__init__.py": b"", "app/billing.py": b"def total(values):\n    return 0\n"}
PREFIX = b"from app.billing import total\n"
BEFORE = PREFIX + b"def test_total():\n    assert total([1, 2]) == 3\n"
AFTER = PREFIX + b"def standin(values):\n    return 3\ndef test_total():\n    assert standin([1, 2]) == 3\n"

TRACED = "tests/test_total.py"
INSTALL_BEFORE = b"import app.billing as billing\ndef test_total():\n    assert billing.total() == 3\n"
INSTALL_AFTER = (b"import app.billing as billing\ndef test_total():\n"
                 b"    billing.total = lambda: 3\n    assert billing.total() == 3\n")


def _source_with_nodes(nodes):
    # Module=1, each literal expression=Expr+Constant=2, pass=1.
    expressions, remainder = divmod(nodes - 1, 2)
    return b"0\n" * expressions + b"pass\n" * remainder


def _nodes(source):
    return sum(1 for _ in ast.walk(ast.parse(source.decode())))


def _analyse(before, after, *, path=PATH, old_path=None):
    changes = [FileChange(path, "modified", before, after, old_path=old_path)]
    sources = {**PRODUCTION, path: after}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 19),
                   root_reader=sources.get, root_path_lister=lambda: sorted(sources),
                   root_batch_reader=lambda paths: {p: sources.get(p) for p in paths})


def _installations():
    sources = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 1\n", TRACED: INSTALL_AFTER}
    return standin.installation_events(
        IR(base="base", head="head", globals=DiffGlobals()),
        [FileChange(TRACED, "modified", INSTALL_BEFORE, INSTALL_AFTER)], Config(),
        root_reader=sources.get, root_path_lister=lambda: sorted(sources),
    )


def _recording(monkeypatch):
    made = []

    class Recording(standin._Trace):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append((self.path, self.side, self.unit))

    monkeypatch.setattr(standin, "_Trace", Recording)
    return made


# Question 1: one node limit for both passes.

def test_the_two_passes_share_one_node_limit():
    assert subject._MAX_SOURCE_NODES is standin._MAX_SOURCE_NODES
    assert subject._MAX_SOURCE_NODES == 200_000


@pytest.mark.parametrize("nodes", [30_001, 200_000])
def test_trees_up_to_the_shared_limit_are_read(nodes):
    source = _source_with_nodes(nodes)
    tree = subject._parse(source, path="tests/test_capacity.py", side="before")
    assert tree is not None
    assert sum(1 for _ in ast.walk(tree)) == nodes


def test_a_test_file_over_the_old_limit_gives_its_verdict():
    padding = b"0\n" * 17_500
    before, after = BEFORE + padding, AFTER + padding
    assert _nodes(before) > 30_000 and _nodes(after) < 200_000
    hits = [f for f in _analyse(before, after)[1] if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1 and hits[0].severity == "high"
    assert "app.billing.total" in hits[0].message


# Question 3: the subject-replacement refusals name path, side and counts.

def test_a_tree_over_the_limit_names_path_side_and_counts():
    source = _source_with_nodes(200_001)
    path = "tests/test_quote'\n::error::injected\t\x1b.py"
    with pytest.raises(EngineError) as caught:
        subject._parse(source, path=path, side="after")
    message = str(caught.value)
    assert message == (NODE_REFUSAL + f"path={path!r}, requested_side='after', "
                       "bytes=200000, nodes=200001, limit=200000")
    assert "\n" not in message and "\r" not in message and "\x1b" not in message


def test_the_byte_limit_names_path_and_side_before_any_parse(monkeypatch):
    source = b"#" + b"x" * 999_999
    assert subject._parse(source, path="tests/test_bytes.py", side="before") is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("an over-limit source must never be parsed")

    monkeypatch.setattr(subject, "parse_text", forbidden)
    with pytest.raises(EngineError) as caught:
        subject._parse(source + b"x", path="tests/test_bytes.py", side="before")
    assert str(caught.value) == (BYTE_REFUSAL + "path='tests/test_bytes.py', requested_side='before', "
                                 "bytes=1000001, limit=1000000")


def test_direct_calls_keep_their_contract_and_name_unknown():
    assert subject._parse(None) is None
    assert subject._parse("pass\n") is None
    assert subject._parse(b"(\n") is None
    with pytest.raises(EngineError) as caught:
        subject._parse(_source_with_nodes(200_001))
    assert str(caught.value).startswith(NODE_REFUSAL + "path='<unknown>', requested_side='<unknown>', ")


@pytest.mark.parametrize("side", ["before", "after"])
def test_the_pass_names_the_refused_side_of_the_changed_test(monkeypatch, side):
    refused = BEFORE if side == "before" else AFTER
    limit = 1 if side == "before" else _nodes(BEFORE)
    assert _nodes(refused) > limit
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", limit)
    with pytest.raises(EngineError) as caught:
        _analyse(BEFORE, AFTER)
    assert str(caught.value) == (NODE_REFUSAL + f"path={PATH!r}, requested_side={side!r}, "
                                 f"bytes={len(refused)}, nodes={_nodes(refused)}, limit={limit}")


def test_a_renamed_test_names_its_old_path_for_the_base_side(monkeypatch):
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", 1)
    with pytest.raises(EngineError) as caught:
        _analyse(BEFORE, AFTER, path="tests/test_billing_renamed.py", old_path=PATH)
    assert str(caught.value) == (NODE_REFUSAL + f"path={PATH!r}, requested_side='before', "
                                 f"bytes={len(BEFORE)}, nodes={_nodes(BEFORE)}, limit=1")


# Question 2 (c) and question 3: the step limits stay and name what fired.

@pytest.mark.parametrize("steps,spent,side,expected", [
    (20_000, 0, 0, "counter=proof, path='tests/test_total.py', requested_side='before', "
                   "unit='TestTotal.test_total', steps=20001, limit=20000"),
    (0, 1_000_000, 1, "counter=analysis, path='tests/test_total.py', requested_side='after', "
                      "unit='TestTotal.test_total', steps=1000001, limit=1000000" + SHARED),
    (20_000, 1_000_000, 1, "counter=proof, path='tests/test_total.py', requested_side='after', "
                           "unit='TestTotal.test_total', steps=20001, limit=20000"),
], ids=["proof", "analysis", "both_name_the_proof"])
def test_the_step_refusal_names_the_counter_that_fired(steps, spent, side, expected):
    trace = standin._Trace([], None, side, set(), [spent], path=TRACED, unit="TestTotal.test_total")
    trace.steps = steps
    with pytest.raises(EngineError) as caught:
        trace._step()
    assert str(caught.value) == STEP_REFUSAL + expected
    assert trace.steps == steps + 1 and trace.budget == [spent + 1]


def test_the_step_refusal_escapes_its_path_and_defaults_to_unknown():
    trace = standin._Trace([], None, 1, set(), [0])
    trace.steps = 20_000
    with pytest.raises(EngineError) as caught:
        trace._step()
    assert str(caught.value).startswith(
        STEP_REFUSAL + "counter=proof, path='<unknown>', requested_side='after', unit='<unknown>', ")
    path = "tests/test_quote'\n::error::injected\x1b.py"
    trace = standin._Trace([], None, None, set(), [1_000_000], path=path, unit="test_x")
    with pytest.raises(EngineError) as caught:
        trace._step()
    message = str(caught.value)
    assert f"path={path!r}, requested_side='<unknown>', unit='test_x', " in message
    assert "\n" not in message and "\x1b" not in message


@pytest.mark.parametrize("limit,value,expected", [
    ("_MAX_ANALYSIS_STEPS", 0, "counter=analysis, path='tests/test_total.py', requested_side='before', "
                               "unit='<module body>', steps=1, limit=0" + SHARED),
    ("_MAX_ANALYSIS_STEPS", 2, "counter=analysis, path='tests/test_total.py', requested_side='after', "
                               "unit='<module body>', steps=3, limit=2" + SHARED),
    ("_MAX_PROOF_STEPS", 2, "counter=proof, path='tests/test_total.py', requested_side='before', "
                            "unit='test_total', steps=3, limit=2"),
    ("_MAX_ANALYSIS_STEPS", 4, "counter=analysis, path='tests/test_total.py', requested_side='before', "
                               "unit='test_total', steps=5, limit=4" + SHARED),
], ids=["seed_before", "seed_after", "test_proof", "test_after_seeds_spent_the_budget"])
def test_each_proof_of_the_pass_is_named_where_it_stops(monkeypatch, limit, value, expected):
    # Each module-body seed takes two steps here (the import and the def);
    # a test's proof replays its module body, then enters the test.
    monkeypatch.setattr(standin, limit, value)
    with pytest.raises(EngineError) as caught:
        _installations()
    assert str(caught.value) == STEP_REFUSAL + expected


def test_each_trace_carries_its_file_side_and_unit(monkeypatch):
    made = _recording(monkeypatch)
    _installations()
    assert made == [(TRACED, 0, "<module body>"), (TRACED, 1, "<module body>"),
                    (TRACED, 0, "test_total"), (TRACED, 1, "test_total")]


def test_the_restructured_patch_proof_is_named_by_its_kind(monkeypatch):
    made = _recording(monkeypatch)
    result = judge_installations({TRACED: TESTCASE_BEFORE.encode()}, {TRACED: TESTCASE_AFTER.encode()})
    assert len(result[0].globals.subject_installations) == 1
    assert made == [(TRACED, 0, "<module body>"), (TRACED, 1, "<module body>"),
                    (TRACED, 1, "<restructured patch>")]


# The owner's choice of 2026-10-19: the pass reads each side's module
# statements once per file, and that changes no result.

SCOPES = b"""import os
def test_a():
    value = 1
    assert value == 1
def test_a():
    assert 2 == 2
async def test_b():
    pass
class TestC:
    def test_d(self):
        pass
    def test_d(self):
        return 1
    class Inner:
        def test_e(self):
            pass
def test_f():
    def inner():
        pass
"""

CAPTURES = PREFIX + (
    b"alias = total\n"
    b"def test_direct():\n    assert total([1, 2]) == 3\n"
    b"def test_capture():\n    value = total([1, 2])\n    assert value == 3\n"
    b"def test_alias():\n    value = alias([1, 2])\n    assert value == 3\n"
    b"def test_rebound():\n    value = total([1, 2])\n    total = sum\n    assert value == 3\n"
    b"class TestGroup:\n    def test_method(self):\n        value = total([1, 2])\n        assert value == 3\n"
)
REPLACED = (CAPTURES.replace(b"alias = total\n", b"alias = total\ndef standin(values):\n    return 3\n")
            .replace(b"value = total(", b"value = standin("))


class _Fresh(subject._ModuleReads):
    """Reads the tree afresh for every question, as the pass did before it kept them."""

    def member(self, scope, name):
        return next((node for node in scope.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and node.name == name), None)

    def star_import(self):
        return any(isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
                   for statement in self.tree.body)

    def sites(self):
        return subject._binding_sites(self.tree.body)

    def values(self):
        return subject._bindings(self.tree.body)

    def inert(self):
        return subject._helper_module_inert(self.tree)

    def top_level(self, node):
        return node in self.tree.body

    def reflective(self):
        return any((isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"globals", "locals", "vars", "exec", "eval", "setattr", "delattr"})
                   or (isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)))
                   for node in ast.walk(self.tree))

    def rebinds(self, name):
        return any(isinstance(node, (ast.Global, ast.Nonlocal, ast.NamedExpr))
                   or isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
                   or isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del))
                   or isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"globals", "locals", "vars", "exec", "eval", "setattr", "delattr"}
                   for node in ast.walk(self.tree))

    def closed_callers(self, replacement, prove):
        return subject._closed_callers(self.tree, replacement, prove)


def _dump(node):
    return None if node is None else ast.dump(node)


def test_the_kept_reads_find_the_scope_the_scan_finds():
    tree = ast.parse(SCOPES)
    reads = subject._ModuleReads(tree)
    names = ["test_a", "test_b", "TestC", "TestC.test_d", "TestC.Inner", "TestC.Inner.test_e", "test_f.inner",
             "test_a.value", "os", "missing", "TestC.missing", "TestC.Inner.test_e.x"]
    for _ in range(2):
        for name in names:
            assert subject._scope(tree, name, reads) is subject._scope(tree, name)
    # The first definition of a name wins, as the scan's first match does.
    assert subject._scope(tree, "test_a", reads) is tree.body[1]
    assert subject._scope(tree, "TestC.test_d", reads) is tree.body[4].body[0]
    assert subject._scope(tree, "TestC.Inner.test_e", reads) is tree.body[4].body[2].body[0]
    assert subject._scope(tree, "TestC", reads) is None


def test_reads_kept_across_a_files_assertions_project_what_fresh_reads_do():
    star = CAPTURES.replace(b"alias = total\n", b"alias = total\nfrom providers import *\n")
    seen = set()
    for source in (CAPTURES, star):
        tree = ast.parse(source)
        reads = subject._ModuleReads(tree)
        for unit in parse_python(source, collect_tests=True).units:
            for assertion in unit.side.assertions:
                for _ in range(2):
                    kept = subject._subject_call(assertion, tree, unit.qualname, reads)
                    assert _dump(kept) == _dump(subject._subject_call(assertion, tree, unit.qualname))
                seen.add((source is star, kept is None))
    # Both files project some assertions and refuse others.
    assert seen == {(False, False), (False, True), (True, False), (True, True)}


def test_the_pass_reads_each_sides_module_statements_once(monkeypatch):
    count = 30
    tests = b"".join(b"def test_%d():\n    value = total([%d])\n    assert value == 3\n" % (n, n) for n in range(count))
    before = PREFIX + tests
    after = before + b"def test_added():\n    assert 1 == 1\n"
    kept, calls, reads = [], [], []

    class Recording(subject._ModuleReads):
        def __init__(self, tree):
            super().__init__(tree)
            kept.append(self)

    def counted(name, original):
        def read(statements):
            if any(statements is module.tree.body for module in kept):
                reads.append(name)
            return original(statements)
        return read

    def call(*args, **kwargs):
        calls.append(args[2])
        return projection(*args, **kwargs)

    projection = subject._subject_call
    monkeypatch.setattr(subject, "_ModuleReads", Recording)
    monkeypatch.setattr(subject, "_binding_sites", counted("sites", subject._binding_sites))
    monkeypatch.setattr(subject, "_bindings", counted("values", subject._bindings))
    monkeypatch.setattr(subject, "_subject_call", call)
    _analyse(before, after)
    # Each pair asks both sides for its subject call; each side's module is read once.
    assert len(kept) == 2
    assert sorted(calls) == sorted(f"test_{n}" for n in range(count) for _ in range(2))
    assert sorted(reads) == ["sites", "sites", "values", "values"]


def test_kept_reads_leave_the_pass_verdicts_as_fresh_reads_give_them(monkeypatch):
    kept = _analyse(CAPTURES, REPLACED)[1]
    monkeypatch.setattr(subject, "_ModuleReads", _Fresh)
    fresh = _analyse(CAPTURES, REPLACED)[1]
    assert kept == fresh
    assert "test_capture" in {f.unit for f in kept if f.rule == "TEST_PATCHES_SUBJECT"}


# The owner's second choice of 2026-10-19: the assertion-helper, changed-callee
# and literal-helper proofs keep their module reads too, and that changes no
# result either.

ORACLE = PREFIX + b"def oracle():\n    assert total([1, 2]) == 3\ndef test_total():\n    oracle()\n"
ORACLE_REPLACED = (ORACLE.replace(b"def oracle():", b"def standin(values):\n    return 3\ndef oracle():")
                   .replace(b"assert total(", b"assert standin("))
CLONE = b"def clone(value):\n    return value.lower()\n"
CLONE_BEFORE = PREFIX + b'def test_total():\n    assert total("Hello") == "hello"\n'
CLONE_AFTER = PREFIX + CLONE + b'def test_total():\n    assert clone("Hello") == "hello"\n'
GCD_BEFORE = PREFIX + b"def test_total():\n    assert total(12, 8) == 4\n"
GCD_AFTER = PREFIX + (b"import math\ndef local_gcd(a, b):\n    return math.gcd(a, b)\n"
                      b"def test_total():\n    assert local_gcd(12, 8) == 4\n")
REFLECTIVE = b"def test_other():\n    globals()['oracle'] = other\n"
UNCLOSED = b"def test_callback():\n    mutate()\n"

WRITES = [
    ORACLE,
    ORACLE + REFLECTIVE,
    ORACLE + b"def test_other():\n    oracle.__code__ = other.__code__\n",
    ORACLE + b"def test_other():\n    del cache[0]\n",
    ORACLE + b"def test_other():\n    global oracle\n",
    ORACLE + b"def test_other():\n    assert (value := 1)\n",
    ORACLE + b"def test_other():\n    standin = total\n",
    ORACLE + b"oracle = other\n",
    b"from provider import *\n" + ORACLE,
    CLONE_AFTER,
    GCD_AFTER,
    SCOPES,
]


def test_kept_reads_answer_the_helper_checks_as_fresh_reads_do():
    seen = {"inert": set(), "reflective": set(), "rebinds": set(), "top_level": set()}
    for source in WRITES:
        tree = ast.parse(source)
        reads, fresh = subject._ModuleReads(tree), _Fresh(tree)
        definitions = [node for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        for _ in range(2):
            assert reads.inert() == fresh.inert()
            assert reads.reflective() == fresh.reflective()
            for name in ("oracle", "standin", "clone", "value", "cache", "missing"):
                assert reads.rebinds(name) == fresh.rebinds(name)
                seen["rebinds"].add(fresh.rebinds(name))
            for node in definitions:
                assert reads.top_level(node) == fresh.top_level(node)
                seen["top_level"].add(fresh.top_level(node))
        seen["inert"].add(fresh.inert())
        seen["reflective"].add(fresh.reflective())
    # Each check answers both ways across these modules.
    assert all(answers == {True, False} for answers in seen.values())


HELPERS = [
    ORACLE,
    ORACLE_REPLACED,
    ORACLE + REFLECTIVE,
    ORACLE + b"oracle = other\n",
    ORACLE.replace(b"def oracle():", b"@decorate\ndef oracle():"),
    ORACLE.replace(b"    oracle()", b"    mutate()\n    oracle()"),
    ORACLE.replace(b"def test_total():", b"def test_total(oracle):"),
    ORACLE.replace(b"assert total([1, 2]) == 3", b"assert total([1, 2]) == 3\n    assert True"),
    ORACLE + b"def test_more():\n    oracle()\n    assert (seen := 1)\n",
    ORACLE + b"def test_twice():\n    oracle()\n    oracle()\n",
    ORACLE + b"class TestGroup:\n    def test_method(self):\n        oracle()\n",
]


def test_kept_reads_locate_each_assertion_helper_as_fresh_reads_do():
    seen = set()
    for source in HELPERS:
        tree = ast.parse(source)
        reads = subject._ModuleReads(tree)
        for unit in parse_python(source, collect_tests=True).units:
            for assertion in unit.side.assertions:
                if not assertion.inherited:
                    continue
                for _ in range(2):
                    kept = subject._assertion_scope(tree, unit.qualname, assertion, reads)
                    assert kept == subject._assertion_scope(tree, unit.qualname, assertion, _Fresh(tree))
                seen.add(kept)
    # Some callers are admitted to the helper and some are refused.
    assert seen == {None, "oracle"}


BINDINGS = PREFIX + b"""import os as system
LIMIT = 3
alias = total
def standin(values):
    return 3
def test_arguments(total, /, alias, *, limit):
    assert total([1, 2]) == 3
def test_reaching():
    value = total([1, 2])
    assert value == 3
def test_local():
    def total(values):
        return 3
    assert total([1, 2]) == 3
class TestGroup:
    def test_method(self, standin):
        assert standin([1, 2]) == 3
"""


def _copied_bindings(tree, qualname, assertion):
    """`_scoped_bindings` as it read before the module's bindings were kept: a fresh copy for each call."""
    bindings = subject._bindings(tree.body)
    scope = subject._scope(tree, qualname)
    if scope is None:
        return None
    for arg in scope.args.posonlyargs + scope.args.args + scope.args.kwonlyargs:
        bindings[arg.arg] = None
    for name, expression in (assertion.reaching or {}).items():
        if expression:
            bindings[name] = parse_expr(expression)
    bindings.update({name: value for name, value in subject._bindings(scope.body).items()
                     if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef))})
    return bindings


def _names(bindings):
    if bindings is None:
        return None
    return {name: ast.dump(bindings[name], include_attributes=True) if isinstance(bindings[name], ast.AST)
            else bindings[name] for name in bindings}


def test_kept_bindings_read_as_the_copy_made_for_each_pair():
    seen = set()
    for source in (BINDINGS, CAPTURES, ORACLE_REPLACED):
        tree = ast.parse(source)
        reads = subject._ModuleReads(tree)
        module = subject._bindings(tree.body)
        for unit in parse_python(source, collect_tests=True).units:
            for assertion in unit.side.assertions:
                for qualname in (unit.qualname, "oracle", "missing"):
                    kept = subject._scoped_bindings(tree, qualname, assertion, reads)
                    copied = _names(_copied_bindings(tree, qualname, assertion))
                    assert _names(kept) == copied
                    # A direct call, with no kept reads, reads the same names.
                    assert _names(subject._scoped_bindings(tree, qualname, assertion)) == copied
                    seen.add(kept is None)
        # No test's names reach the kept module bindings.
        assert reads.values() == module
    assert seen == {True, False}


@pytest.mark.parametrize("shape", ["helper", "callee"])
def test_the_pass_reads_each_sides_module_once_for_helper_and_changed_callee_tests(monkeypatch, shape):
    count = 30
    if shape == "helper":
        callers = b"".join(b"def test_%d():\n    oracle()\n" % n for n in range(count))
        before = ORACLE.replace(b"def test_total():\n    oracle()\n", callers)
        after = ORACLE_REPLACED.replace(b"def test_total():\n    oracle()\n", callers)
        expected = ["inert", "inert", "sites", "sites", "values", "values", "walk", "walk"]
    else:
        tests = b"".join(b'def test_%d():\n    assert CALLEE("A%d") == "a%d"\n' % (n, n, n) for n in range(count))
        before = PREFIX + tests.replace(b"CALLEE", b"total")
        after = PREFIX + CLONE + tests.replace(b"CALLEE", b"clone")
        expected = ["callers", "inert", "values", "values", "walk"]
    kept, reads, calls = [], [], []

    class Recording(subject._ModuleReads):
        def __init__(self, tree):
            super().__init__(tree)
            kept.append(self)

    def body_read(name, original):
        def read(statements):
            if any(statements is module.tree.body for module in kept):
                reads.append(name)
            return original(statements)
        return read

    def tree_read(name, original):
        def read(tree, *args, **kwargs):
            if any(tree is module.tree for module in kept):
                reads.append(name)
            return original(tree, *args, **kwargs)
        return read

    def counted(name, original):
        def call(*args, **kwargs):
            calls.append(name)
            return original(*args, **kwargs)
        return call

    monkeypatch.setattr(subject, "_ModuleReads", Recording)
    monkeypatch.setattr(subject, "_binding_sites", body_read("sites", subject._binding_sites))
    monkeypatch.setattr(subject, "_bindings", body_read("values", subject._bindings))
    monkeypatch.setattr(subject, "_helper_module_inert", tree_read("inert", subject._helper_module_inert))
    monkeypatch.setattr(subject, "_closed_callers", tree_read("callers", subject._closed_callers))
    # Only walks of a kept tree count; `_parse` counts each tree's nodes before it is kept.
    monkeypatch.setattr(ast, "walk", tree_read("walk", ast.walk))
    monkeypatch.setattr(subject, "_assertion_scope", counted("scope", subject._assertion_scope))
    monkeypatch.setattr(subject, "_scoped_bindings", counted("bindings", subject._scoped_bindings))
    findings = _analyse(before, after)[1]
    # Each pair asks both sides; each side's module is read once.
    assert len(kept) == 2
    assert calls.count("scope") == calls.count("bindings") == 2 * count
    assert sorted(reads) == expected
    # Every test's replacement is still found.
    assert {f"test_{n}" for n in range(count)} <= {f.unit for f in findings if f.rule == "TEST_PATCHES_SUBJECT"}


def test_kept_reads_leave_helper_and_changed_callee_verdicts_as_fresh_reads_give_them(monkeypatch):
    more = b'def test_more():\n    assert CALLEE("World") == "world"\n'
    cases = [
        (ORACLE, ORACLE_REPLACED, True),
        (ORACLE + REFLECTIVE, ORACLE_REPLACED + REFLECTIVE, None),
        (BEFORE, AFTER, True),
        (CAPTURES, REPLACED, True),
        (CLONE_BEFORE, CLONE_AFTER, True),
        (CLONE_BEFORE + more.replace(b"CALLEE", b"total"), CLONE_AFTER + more.replace(b"CALLEE", b"clone"), True),
        (CLONE_BEFORE + UNCLOSED, CLONE_AFTER + UNCLOSED, False),
        (GCD_BEFORE, GCD_AFTER, True),
        (GCD_BEFORE + UNCLOSED, GCD_AFTER + UNCLOSED, False),
    ]
    kept = [_analyse(before, after)[1] for before, after, _ in cases]
    monkeypatch.setattr(subject, "_ModuleReads", _Fresh)
    fresh = [_analyse(before, after)[1] for before, after, _ in cases]
    assert kept == fresh
    for (_, _, expected), findings in zip(cases, kept):
        if expected is not None:
            assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings) is expected


# The owner's third choice of 2026-10-19: the `math.gcd` import authority and
# the parameterized-helper checks are made once per file, and that changes no
# result either.

GCD_HELPER = b"import math\ndef local_gcd(a, b):\n    return math.gcd(a, b)\n"
CHECK_VALUE = b"def check_value(value, expected):\n    assert abs(value) == expected\n"


def _gcd_rows(count):
    """`count` tests whose callee changed to a local `math.gcd` helper."""
    tests = b"".join(b"def test_%d():\n    assert CALLEE(%d, 8) == 4\n" % (n, 4 * (2 * n + 1)) for n in range(count))
    return PREFIX + tests.replace(b"CALLEE", b"total"), PREFIX + GCD_HELPER + tests.replace(b"CALLEE", b"local_gcd")


def _abs_rows(count):
    """`count` tests whose literal row became a call of one parameterized `abs` helper."""
    before = PREFIX + b"".join(b"def test_%d():\n    assert total(-%d) == %d\n" % (n, n + 1, n + 1) for n in range(count))
    after = PREFIX + CHECK_VALUE + b"".join(b"def test_%d():\n    check_value(-%d, %d)\n" % (n, n + 1, n + 1)
                                            for n in range(count))
    return before, after


def _context(after):
    sources = {**PRODUCTION, PATH: after}
    return ConftestContext([FileChange(PATH, "modified", BEFORE, after)], sources.get), (lambda _needles: sorted(sources))


def test_a_kept_math_gcd_authority_answers_as_a_fresh_check_does():
    cases = [
        (GCD_AFTER, "app.billing.total", ["total(12, 8)", "total(4, 6)"]),
        (GCD_AFTER, "app.billing.total", ["other(12, 8)", "total(12, 8)"]),
        (GCD_AFTER, "app.billing.other", ["total(12, 8)"]),
        (GCD_AFTER.replace(b"import math\n", b"import math\nimport os\n"), "app.billing.total", ["total(12, 8)"]),
        # Over 65,536 bytes, `pure_imported_calls` refuses the test source.
        (GCD_AFTER + b"pass\n" * 20_000, "app.billing.total", ["total(12, 8)"]),
    ]
    seen = set()
    for source, target, calls in cases:
        tree = ast.parse(source)
        context, search = _context(source)
        kept = {}
        for text in calls:
            call = parse_expr(text)
            for _ in range(2):
                answer = literal_stdlib.math_import_authority(source, tree, call, target, PATH, context, search, kept)
                assert answer == literal_stdlib.math_import_authority(source, tree, call, target, PATH, *_context(source))
            seen.add(answer)
        # Calls of one callee share one kept answer.
        assert len(kept) == len({parse_expr(text).func.id for text in calls})
    # The check admits some sources and calls and refuses others.
    assert seen == {True, False}


@pytest.mark.parametrize("shape", ["gcd", "parameterized"])
def test_the_pass_checks_math_gcd_and_parameterized_tests_once_per_file(monkeypatch, shape):
    count = 30
    asked, checked, trees = [], [], []

    def counted(name, original, tree_at=None):
        def call(*args, **kwargs):
            if tree_at is None or any(args[tree_at] is tree for tree in trees):
                checked.append(name)
            return original(*args, **kwargs)
        return call

    if shape == "gcd":
        before, after = _gcd_rows(count)
        authority = subject.math_import_authority

        def ask(*args):
            asked.append(args[2])
            return authority(*args)

        monkeypatch.setattr(subject, "math_import_authority", ask)
        monkeypatch.setattr(literal_stdlib, "pure_imported_calls", counted("source", literal_stdlib.pure_imported_calls))
        monkeypatch.setattr(literal_stdlib, "inert_test_execution_context",
                            counted("startup", literal_stdlib.inert_test_execution_context))
        expected = ["source", "startup"]
    else:
        before, after = _abs_rows(count)
        event = subject.parameterized_abs_event

        def ask(*args):
            asked.append(args[0])
            if not trees:
                # Every test of the file passes the same two trees.
                trees.extend(args[1])
            return event(*args)

        monkeypatch.setattr(subject, "parameterized_abs_event", ask)
        # Only reads of the trees this pass checks count; other passes read their own.
        monkeypatch.setattr(subject, "_helper_module_inert", counted("inert", subject._helper_module_inert, 0))
        monkeypatch.setattr(replacement_authority, "closed_replacement_authority",
                            counted("authority", replacement_authority.closed_replacement_authority, 0))
        expected = ["authority", "inert", "inert"]
    findings = [f for f in _analyse(before, after)[1] if f.rule == "TEST_PATCHES_SUBJECT"]
    # Every test asks; the checks are made once for the file.
    assert len(asked) == count
    assert sorted(checked) == expected
    # Every test's replacement is still found, each at its own first call.
    assert {f"test_{n}" for n in range(count)} <= {f.unit for f in findings}
    if shape == "parameterized":
        assert {(f"test_{n}", f"check_value(-{n + 1}, {n + 1})") for n in range(count)} <= {
            (f.unit, f.after.text) for f in findings}


def test_kept_checks_leave_math_gcd_and_parameterized_verdicts_as_fresh_checks_give_them(monkeypatch):
    abs_before, abs_after = _abs_rows(2)
    gcd_before, gcd_after = _gcd_rows(2)
    cases = [
        (abs_before, abs_after, True),
        (abs_before, abs_after.replace(b"check_value(-2, 2)", b"check_value(-2, 3)"), False),
        (abs_before, abs_after + UNCLOSED, False),
        (gcd_before, gcd_after, True),
        (gcd_before, gcd_after.replace(b"import math\n", b"import math\nimport os\n"), False),
        (gcd_before + UNCLOSED, gcd_after + UNCLOSED, False),
    ]
    kept = [_analyse(before, after)[1] for before, after, _ in cases]
    event, authority = subject.parameterized_abs_event, subject.math_import_authority
    # Without the dicts the pass keeps, each test is checked afresh.
    monkeypatch.setattr(subject, "parameterized_abs_event", lambda *args: event(*args[:7]))
    monkeypatch.setattr(subject, "math_import_authority", lambda *args: authority(*args[:7]))
    fresh = [_analyse(before, after)[1] for before, after, _ in cases]
    assert kept == fresh
    for (_, _, expected), findings in zip(cases, kept):
        assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings) is expected
