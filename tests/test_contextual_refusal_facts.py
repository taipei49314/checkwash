"""Finite source diagnostic controls; hosted execution remains NOT_RUN."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from test_subject_call_prefilter import paired

from checkwash import cli
from checkwash.change import EngineError
from checkwash.frontends.python import subject_replacements as subject
from checkwash.gitio.snapshot import GitSnapshot
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion

NODE_MESSAGE = "subject replacement source exceeds the syntax node limit"
MODE_MESSAGE = "strict snapshot batch cannot inspect nonregular source"
LARGE = b"pass\n" * 30_000  # Module +30000 Pass nodes =30001, below byte bound.


def test_exact_node_boundary_and_real_over_bound_keep_original_message():
    assert subject._parse(b"pass\n" * 29_999) is not None  # Exactly30000 nodes.
    with pytest.raises(EngineError) as raised:
        subject._parse(LARGE)
    assert str(raised.value) == NODE_MESSAGE
    assert raised.value.source_refusal_diagnostic == {
        "layer": "subject_replacement", "reason": "syntax_node_limit",
        "path": None, "requested_side": None, "unit": None,
        "pair_before_id": None, "pair_after_id": None, "trigger": None,
        "source_bytes": len(LARGE), "observed_nodes": 30_001, "node_limit": 30_000,
    }


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("trigger", ["assertion_pair", "parameterized_inherited"])
def test_both_actual_module_callers_preserve_path_side_unit_and_available_pair(side, trigger):
    before, after = (LARGE, b"pass\n") if side == "before" else (b"pass\n", LARGE)
    ir, change, _old, _new = paired("billing.total()", "sum()", before, after)
    unit = ir.files[0].units[0]
    if trigger == "parameterized_inherited":
        unit.after.assertions.append(Assertion(
            "a1", "compare_eq", S.EXACT_VALUE, "assert got == expected", (2, 3),
            left="got", right_literal=None, inherited=True))
    with pytest.raises(EngineError) as raised:
        subject.subject_replacement_events(ir, [change], root_reader=lambda _path: None)
    assert str(raised.value) == NODE_MESSAGE
    fact = raised.value.source_refusal_diagnostic
    assert (fact["path"], fact["requested_side"], fact["unit"], fact["trigger"]) == (
        change.path, side, unit.qualname, trigger)
    expected_pair = ("a0", "a0") if trigger == "assertion_pair" else (None, None)
    assert (fact["pair_before_id"], fact["pair_after_id"]) == expected_pair
    assert (fact["source_bytes"], fact["observed_nodes"], fact["node_limit"]) == (
        len(LARGE), 30_001, 30_000)


def test_other_parse_refusal_keeps_default_and_original_exception_identity(monkeypatch):
    failure = EngineError("owned existing parse refusal")
    def failed(data):
        assert data == b"owned"
        raise failure
    monkeypatch.setattr(subject, "_parse", failed)
    with pytest.raises(EngineError) as raised:
        subject._parse_with_context(b"owned", path="tests/test_owned.py", side="before",
                                    unit="test_owned", trigger="assertion_pair", pair_ids=("b0", "a0"))
    assert raised.value is failure and failure.source_refusal_diagnostic is None


def test_strict_nonregular_batch_records_actual_selected_path_mode_oid_and_revision(monkeypatch):
    snapshot = GitSnapshot("unused", "owned-symbolic-revision")
    snapshot._resolved = "1" * 40
    snapshot._opaque = ()
    path = "tests/test_中文.py"
    snapshot._tree_entries = {path: (b"120000", b"2" * 40, 12)}
    def forbidden(_present):
        pytest.fail("nonregular refusal must precede blob transport")
    monkeypatch.setattr(snapshot, "_read_objects", forbidden)
    with pytest.raises(EngineError) as raised:
        snapshot.read_many([path, "absent.py", path])
    assert str(raised.value) == MODE_MESSAGE
    assert raised.value.source_refusal_diagnostic == {
        "layer": "strict_snapshot_batch", "reason": "nonregular_source",
        "revision": "1" * 40, "path": path, "mode": "120000", "oid": "2" * 40,
        "request_count": 2,  # Actual deduplicated sorted request, not three input items.
    }


@pytest.mark.parametrize("format_name", ["term", "json", "sarif"])
def test_cli_preserves_legacy_text_exit_two_and_empty_public_stdout(monkeypatch, capsys, format_name):
    def failed(_args):
        subject._parse_with_context(LARGE, path="tests/test_owned.py", side="before",
                                    unit="test_owned", trigger="assertion_pair", pair_ids=("b0", "a0"))
    monkeypatch.setattr(cli, "_cmd_check", failed)
    assert cli.main(["check", "--format", format_name]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "checkwash engine error: EngineError: " + NODE_MESSAGE + "\n"


def test_collector_forwards_only_named_optional_scalar_facts_and_keeps_default_absence(monkeypatch):
    # exception_fact has no resource use; stub only this Linux helper import
    # so its actual function can be checked on every qualification platform.
    monkeypatch.setitem(sys.modules, "resource", types.ModuleType("resource"))
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("owned_refusal_diagnostic", root / "tools/standin_cost_diagnostic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plain = EngineError("owned unrelated error")
    assert "source_refusal_diagnostic" not in module.exception_fact(plain)
    error = EngineError(NODE_MESSAGE)
    error.source_refusal_diagnostic = {
        "layer": "subject_replacement", "path": "tests/test_中文.py",
        "observed_nodes": 30_001, "unit": None, "request_count": True,
        "unrequested_secret": "must not be forwarded", "source_bytes": object(),
    }
    fact = module.exception_fact(error)
    assert fact["message"] == NODE_MESSAGE
    assert fact["source_refusal_diagnostic"] == {
        "layer": "subject_replacement", "path": "tests/test_中文.py",
        "observed_nodes": 30_001, "unit": None,
    }
