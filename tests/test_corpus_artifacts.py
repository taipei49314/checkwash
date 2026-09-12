"""Partial or stale CI artifacts cannot establish matrix determinism."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("corpus_artifacts", ROOT / "tools/corpus_artifacts.py")
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)


def context():
    return {
        "checkout_sha": "a" * 40, "candidate_head": "b" * 40,
        "run_id": "1234", "run_attempt": "2", "tree_sha": "c" * 40,
        "src_tree_sha": "d" * 40, "cases_tree_sha": "e" * 40,
        "emitter_blob_sha": "f" * 40, "case_names": ["first.gwcase", "second.gwcase"],
    }


def payload(names=None, *, label="before"):
    names = context()["case_names"] if names is None else names
    findings = {
        "checkwash_findings_version": 2, "verdict": "pass", "findings": [],
        "run": {"base": label, "head": "after", "checkwash_version": "0.3.3"},
        "summary": {"critical": 0, "high": 0, "warn": 0, "info": 0},
        "config_errors": [], "skipped_files": [],
    }
    ir = {"version": 2, "base": label, "head": "after", "files": [], "globals": {}}
    return "".join(f"# {name}\n" + json.dumps(findings) + "\n" + json.dumps(ir) + "\n"
                   for name in names).encode()


def write_artifact(folder, ctx, os_name, version, data=None):
    data = payload(ctx["case_names"]) if data is None else data
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "corpus-findings.json").write_bytes(data)
    (folder / "emitter-stderr.txt").write_bytes(b"")
    receipt = ARTIFACTS.make_receipt(ctx, os_name, version, data, b"")
    (folder / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def matrix(tmp_path, ctx=None):
    ctx = context() if ctx is None else ctx
    for os_name, version in ARTIFACTS.MATRIX:
        name = ARTIFACTS.artifact_name(os_name, version, ctx["run_attempt"])
        write_artifact(tmp_path / name, ctx, os_name, version)
    return tmp_path / ARTIFACTS.artifact_name(*ARTIFACTS.MATRIX[0], ctx["run_attempt"])


def test_complete_source_bound_matrix_passes(tmp_path):
    matrix(tmp_path)
    result = ARTIFACTS.compare(tmp_path, context())
    assert result["artifact_count"] == 9
    assert result["status"] == "passed"
    assert result["checkout_sha"] != result["candidate_head"]  # PR merge snapshot is explicit.


@pytest.mark.parametrize("damage", ["missing-leg", "extra-leg", "missing-file", "extra-file"])
def test_requires_exact_artifact_and_file_inventory(tmp_path, damage):
    first = matrix(tmp_path)
    if damage == "missing-leg":
        for file in first.iterdir():
            file.unlink()
        first.rmdir()
    elif damage == "extra-leg":
        (tmp_path / "corpus-other-py3.12-attempt-2").mkdir()
    elif damage == "missing-file":
        (first / "receipt.json").unlink()
    else:
        (first / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ARTIFACTS.compare(tmp_path, context())


@pytest.mark.parametrize("field", [
    "schema", "checkout_sha", "candidate_head", "run_id", "run_attempt", "tree_sha",
    "src_tree_sha", "cases_tree_sha", "emitter_blob_sha", "os", "python", "case_names",
    "payload_sha256", "payload_bytes", "stderr_sha256", "stderr_bytes",
])
def test_rejects_wrong_identity_or_self_reported_content(tmp_path, field):
    first = matrix(tmp_path)
    path = first / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt[field] = "wrong"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="identity, inventory or content hash mismatch"):
        ARTIFACTS.compare(tmp_path, context())


@pytest.mark.parametrize("damage", ["empty", "truncated", "missing", "duplicate", "extra", "reordered", "garbage"])
def test_incomplete_stream_is_rejected_even_with_updated_digest(tmp_path, damage):
    first = matrix(tmp_path)
    good = payload()
    damaged = {
        "empty": b"", "truncated": good[:-8], "missing": payload(["first.gwcase"]),
        "duplicate": payload(["first.gwcase", "first.gwcase"]),
        "extra": good + payload(["third.gwcase"]),
        "reordered": payload(["second.gwcase", "first.gwcase"]), "garbage": good + b"garbage",
    }[damage]
    (first / "corpus-findings.json").write_bytes(damaged)
    path = first / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt.update(payload_sha256=ARTIFACTS.digest(damaged), payload_bytes=len(damaged))
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        ARTIFACTS.compare(tmp_path, context())


def test_nine_identical_partial_streams_cannot_claim_a_smaller_inventory(tmp_path):
    partial = {**context(), "case_names": ["first.gwcase"]}
    matrix(tmp_path, partial)
    with pytest.raises(ValueError):
        ARTIFACTS.compare(tmp_path, context())


def test_complete_valid_payload_drift_is_compared_as_original_bytes(tmp_path):
    first = matrix(tmp_path)
    write_artifact(first, context(), *ARTIFACTS.MATRIX[0], payload(label="different"))
    with pytest.raises(ValueError, match="matrix corpus bytes differ"):
        ARTIFACTS.compare(tmp_path, context())
    assert b"different" in (first / "corpus-findings.json").read_bytes()


@pytest.mark.parametrize("damage", ["empty-object", "duplicate-key", "non-finite", "crlf"])
def test_invalid_json_envelopes_are_not_complete_payloads(damage):
    data = payload()
    data = {
        "empty-object": b"# first.gwcase\n{}\n{}\n# second.gwcase\n{}\n{}\n",
        "duplicate-key": data.replace(b'"version": 2', b'"version": 2, "version": 2'),
        "non-finite": data.replace(b'"base": "before"', b'"base": NaN'),
        "crlf": data.replace(b"\n", b"\r\n"),
    }[damage]
    with pytest.raises(ValueError):
        ARTIFACTS.validate_payload(data, context()["case_names"])


def test_emitter_failure_preserves_raw_output_without_a_success_receipt(tmp_path, monkeypatch):
    ctx = context()
    monkeypatch.setattr(ARTIFACTS, "source_context", lambda *_args: ctx)
    monkeypatch.setattr(ARTIFACTS.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ARTIFACTS.subprocess, "run",
                        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2, b"partial bytes", b""))
    args = argparse.Namespace(checkout_sha=ctx["checkout_sha"], candidate_head=ctx["candidate_head"],
                              run_id=ctx["run_id"], attempt=ctx["run_attempt"], os="ubuntu-latest",
                              python=f"{sys.version_info.major}.{sys.version_info.minor}", output=tmp_path)
    with pytest.raises(ValueError, match="emitter exited 2"):
        ARTIFACTS.emit(args)
    assert (tmp_path / "corpus-findings.json").read_bytes() == b"partial bytes"
    assert not (tmp_path / "receipt.json").exists()


def test_source_context_change_prevents_success_receipt(tmp_path, monkeypatch):
    ctx = context()
    contexts = iter([ctx, {**ctx, "tree_sha": "0" * 40}])
    monkeypatch.setattr(ARTIFACTS, "source_context", lambda *_args: next(contexts))
    monkeypatch.setattr(ARTIFACTS.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ARTIFACTS.subprocess, "run",
                        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, payload(), b""))
    args = argparse.Namespace(checkout_sha=ctx["checkout_sha"], candidate_head=ctx["candidate_head"],
                              run_id=ctx["run_id"], attempt=ctx["run_attempt"], os="ubuntu-latest",
                              python=f"{sys.version_info.major}.{sys.version_info.minor}", output=tmp_path)
    with pytest.raises(ValueError, match="source context changed"):
        ARTIFACTS.emit(args)
    assert (tmp_path / "corpus-findings.json").read_bytes() == payload()
    assert not (tmp_path / "receipt.json").exists()
