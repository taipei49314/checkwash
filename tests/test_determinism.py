"""Determinism: identical inputs must yield byte-identical findings JSON (SPEC §8)."""

import datetime
import pathlib

from greenwash.cases import case_to_changes, parse_case
from greenwash.config import Config
from greenwash.contract import Contract, parse_contract
from greenwash.engine import analyze
from greenwash.report.jsonout import findings_to_json, ir_to_json

CASES = sorted((pathlib.Path(__file__).parent / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)


def _run_corpus() -> str:
    chunks = []
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        ir, findings, verdict = analyze(case_to_changes(case), Config(), contract, [], TODAY)
        chunks.append(findings_to_json(ir, findings, verdict))
        chunks.append(ir_to_json(ir))
    return "".join(chunks)


def test_double_run_byte_identical():
    assert _run_corpus() == _run_corpus()


def test_set_literals_are_hash_seed_independent():
    """A set literal's repr depends on hash randomisation.

    `repr({"a", "b"})` differs per PYTHONHASHSEED, and that string reaches
    finding messages and the IR — so an expectation containing a set literal
    made output non-reproducible, breaking SPEC §8. Sets are canonicalised
    to sorted order; this pins it across seeds in real subprocesses.
    """
    import os
    import subprocess
    import sys

    snippet = (
        "import ast, sys;"
        "sys.path.insert(0, 'src');"
        "from greenwash.frontends.python.frontend import _literal_value;"
        "print(_literal_value(ast.parse('{\"d\",\"c\",\"b\",\"a\"}', mode='eval').body))"
    )
    outputs = set()
    for seed in ("0", "1", "42", "12345", "99999"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            cwd=str(pathlib.Path(__file__).resolve().parent.parent),
            env=env,
        )
        outputs.add(proc.stdout.decode().strip())
    assert len(outputs) == 1, f"set repr varies with hash seed: {outputs}"
    assert outputs == {"{'a', 'b', 'c', 'd'}"}


def test_corpus_emitter_writes_bytes_not_text():
    """tools/emit_corpus.py must not go through text-mode stdout.

    Text mode translates \\n to \\r\\n on Windows, so the harness that proves
    the byte-identical claim emitted different bytes per OS and the CI
    byte-compare job failed — while the product path was always correct.
    """
    import os
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "emit_corpus.py")],
        capture_output=True,
        cwd=str(root),
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert proc.returncode == 0, proc.stderr.decode()[:400]
    assert proc.stdout, "emitter produced nothing"
    # The artifact CI byte-compares must contain no CR, on any OS.
    assert b"\r" not in proc.stdout, "corpus artifact contains CR — text-mode stdout"


def test_no_timestamps_in_findings():
    out = _run_corpus()
    assert "duration" not in out
    assert "timestamp" not in out
