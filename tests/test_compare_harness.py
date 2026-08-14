"""The compare harness must fail closed when a clone or CLI is missing."""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN_PY = ROOT / "benchmarks" / "compare" / "run.py"
PREPARE_PY = ROOT / "benchmarks" / "compare" / "prepare.py"


def test_run_py_usage_on_wrong_argc():
    proc = subprocess.run(
        [sys.executable, str(RUN_PY)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr
    assert "README.md" in proc.stderr


def test_run_py_names_missing_paths(tmp_path):
    out = tmp_path / "out.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(RUN_PY),
            sys.executable,
            str(tmp_path / "no-such-cli.js"),
            str(tmp_path / "no-b"),
            str(tmp_path / "no-a"),
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "missing" in proc.stderr
    assert "swarm-cli-js" in proc.stderr
    assert "decoy_b" in proc.stderr
    assert not out.exists()


def test_prepare_py_usage():
    proc = subprocess.run(
        [sys.executable, str(PREPARE_PY)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


def test_prepare_materializes_both_arms(tmp_path):
    dest = tmp_path / "compare"
    proc = subprocess.run(
        [sys.executable, str(PREPARE_PY), str(dest)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    arm_b = dest / "arm-b"
    arm_a = dest / "arm-a"
    b_repos = [p for p in arm_b.iterdir() if (p / ".git").exists()]
    a_repos = [p for p in arm_a.iterdir() if (p / ".git").exists()]
    assert len(b_repos) == 12, proc.stdout
    assert len(a_repos) == 12, proc.stdout
    assert "run.py" in proc.stdout
