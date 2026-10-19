"""Issue #469: the subject-replacement node limit and the stand-in step limits.

Ruling 469 (owner, 2026-10-18). The subject-replacement pass reads the
stand-in pass's 200,000-node limit, so a test file over the old 30,000 nodes
gives a verdict; its node and byte refusals name the path, the requested side
and the counts. The stand-in step limits stay, and their refusal names which
counter fired, the file, the side, the unit and that counter's steps and
limit. Source bytes are parsed only; the sources here are never executed.
"""

import ast
import datetime

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import standin_installations as standin
from checkwash.frontends.python import subject_replacements as subject
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
