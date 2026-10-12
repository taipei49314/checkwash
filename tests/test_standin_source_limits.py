"""Owned #345 node/byte boundaries and honest source diagnostics.

Source bytes are parsed only. Real CLI coverage uses an owned Git repository;
the synthetic target source is never imported or executed.
"""

import ast
import os
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.frontends.python import standin_installations as subject
from checkwash.ir.model import IR, DiffGlobals


def _source_with_nodes(nodes):
    # Module=1, each literal expression=Expr+Constant=2, pass=1.
    expressions, remainder = divmod(nodes - 1, 2)
    return b"0\n" * expressions + b"pass\n" * remainder


@pytest.mark.parametrize("nodes", [199_999, 200_000])
def test_real_trees_at_and_below_the_ruled_limit_are_readable(nodes):
    source = _source_with_nodes(nodes)
    assert len(source) < 1_000_000
    tree = subject._syntax(source, path="tests/test_capacity.py", side="before")
    assert tree is not None
    assert sum(1 for _ in ast.walk(tree)) == nodes


def test_real_tree_above_limit_reports_full_count_and_escaped_path():
    source = _source_with_nodes(200_007)
    path = "tests/test_quote'\n::error::injected\t\x1b.py"
    with pytest.raises(EngineError) as caught:
        subject._syntax(source, path=path, side="after")
    message = str(caught.value)
    assert "stand-in source exceeds the syntax node limit" in message
    assert f"path={path!r}" in message
    assert "requested_side='after'" in message
    assert f"bytes={len(source)}, nodes=200007, limit=200000" in message
    assert "\n" not in message and "\r" not in message and "\x1b" not in message


def test_exact_byte_limit_remains_readable_and_over_limit_precedes_parse(monkeypatch):
    source = b"#" + b"x" * 999_999
    assert subject._syntax(source, path="tests/test_bytes.py", side="before") is not None

    def forbidden_parse(*args, **kwargs):
        raise AssertionError("over-byte-limit input must never reach ast.parse")

    monkeypatch.setattr(subject.ast, "parse", forbidden_parse)
    path = "tests/test_bytes\n::notice::owned.py"
    with pytest.raises(EngineError) as caught:
        subject._syntax(source + b"x", path=path, side="after")
    message = str(caught.value)
    assert "stand-in source exceeds the byte limit" in message
    assert f"path={path!r}" in message
    assert "bytes=1000001, limit=1000000" in message
    assert "nodes=" not in message
    assert "\n" not in message


@pytest.mark.parametrize("caller,side", [
    ("candidate", "after"), ("imports", "before"),
    ("rebind_before", "before"), ("rebind_after", "after"),
    ("module", "after"), ("assignment_before", "before"), ("assignment_after", "after"),
])
def test_all_syntax_callers_keep_logical_path_and_requested_side(monkeypatch, caller, side):
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", 8)
    large, small = _source_with_nodes(21), b"pass\n"
    path = "tests/test_selected.py"
    with pytest.raises(EngineError) as caught:
        if caller == "candidate":
            subject._candidate(large, path=path, side=side)
        elif caller == "imports":
            subject._imports(large, path=path, side=side)
        elif caller == "rebind_before":
            subject._import_rebind(large, small, path=path)
        elif caller == "rebind_after":
            subject._import_rebind(small, large, path=path)
        elif caller == "module":
            subject._module(path, large, "", side=side)
        elif caller == "assignment_before":
            subject._new_assignment_candidate((large, small), path=path)
        else:
            subject._new_assignment_candidate((small, large), path=path)
    message = str(caught.value)
    assert f"path={path!r}" in message
    assert f"requested_side={side!r}" in message
    assert "nodes=21, limit=8" in message


@pytest.mark.parametrize("side", ["before", "after"])
def test_installation_scheduling_retains_the_changed_file_side(monkeypatch, side):
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", 8)
    large, small = _source_with_nodes(21), b"pass\n"
    before, after = (large, small) if side == "before" else (small, large)
    path = "tests/test_changed.py"
    with pytest.raises(EngineError) as caught:
        subject.installation_events(
            IR(base="base", head="head", globals=DiffGlobals()),
            [FileChange(path, "modified", before, after)], Config(),
            root_reader=lambda path: None,
        )
    assert f"path={path!r}" in str(caught.value)
    assert f"requested_side={side!r}" in str(caught.value)


def test_unchanged_oversized_consumer_names_root_reader_provenance():
    installation = b"import app.billing as billing\nbilling.total = lambda: 3\n"
    path = "tests/test_consumer.py"
    sources = {path: b"#" + b"x" * 1_000_000}
    with pytest.raises(EngineError) as caught:
        subject.installation_events(
            IR(base="base", head="head", globals=DiffGlobals()),
            [FileChange("conftest.py", "added", None, installation)], Config(),
            root_reader=sources.get, root_path_lister=lambda: sorted(sources),
        )
    message = str(caught.value)
    assert "stand-in context exceeds the source byte limit" in message
    assert f"path={path!r}" in message
    assert "requested_side='before', source='root_reader'" in message
    assert "bytes=1000001, limit=1000000" in message


def test_legacy_direct_calls_and_parse_failure_contract_are_unchanged(monkeypatch):
    assert subject._syntax(None) is None
    assert subject._syntax(b"(\n") is None
    assert subject._candidate(b"pass\n") is False
    assert subject._imports(b"import app\n") == {"app"}
    assert subject._new_assignment_candidate((b"pass\n", b"pass\n")) is False
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", 8)
    with pytest.raises(EngineError) as caught:
        subject._syntax(_source_with_nodes(21))
    assert "path='<unknown>', requested_side='<unknown>'" in str(caught.value)


def _git(repo, *args):
    run = subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout.strip()


def test_real_cli_over_node_limit_remains_exit2_and_names_file_and_count(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "owned issue345 boundary")
    _git(tmp_path, "config", "user.email", "issue345@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    target = tmp_path / "tests/test_capacity.py"
    target.parent.mkdir()
    target.write_bytes(b"pass\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned small base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    target.write_bytes(_source_with_nodes(200_001))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned over-limit head")
    head = _git(tmp_path, "rev-parse", "HEAD")
    run = subprocess.run(
        [sys.executable, "-B", "-m", "checkwash", "check", f"{base}..{head}",
         "--repo", str(tmp_path), "--format", "json"],
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=90,
        env={**os.environ, "PYTHONUTF8": "1", "NO_COLOR": "1"},
    )
    assert run.returncode == 2, run.stdout + run.stderr
    assert not run.stdout.strip(), "engine refusal must not be presented as a verdict"
    assert "stand-in source exceeds the syntax node limit" in run.stderr
    assert "path='tests/test_capacity.py', requested_side='after'" in run.stderr
    assert "nodes=200001, limit=200000" in run.stderr
