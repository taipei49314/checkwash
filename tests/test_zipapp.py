"""The single-file build is a shipped surface, so it is gated like the rest.

greenwash has zero runtime dependencies and a single console entry point,
which makes `python -m zipapp` a real distribution channel rather than a
trick: one 0.5 MB file, no install, no virtualenv, no network. That is the
shortest path from "I read the README" to "I have a verdict on my repo", and
the shortest path is the one most likely to rot unnoticed.

Two things can break it and neither shows up anywhere else: a runtime
dependency creeping into pyproject (the zipapp would import it and die), and
package data read by a path instead of `importlib.resources` (inside a zip
there are no paths). The demo is the canary for the second — its cases live
in `src/greenwash/demo_cases/` and are loaded exactly the way a pipx install
loads them.
"""

import os
import subprocess
import sys
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build(tmp_path: Path) -> Path:
    target = tmp_path / "greenwash.pyz"
    zipapp.create_archive(ROOT / "src", target=target, main="greenwash.cli:main", compressed=True)
    return target


def _run(pyz: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(pyz), *args],
        capture_output=True,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def test_zipapp_builds_and_reports_its_version(tmp_path):
    pyz = _build(tmp_path)
    assert pyz.stat().st_size < 4_000_000, "single-file build should stay small enough to attach to a release"
    from greenwash import __version__

    out = _run(pyz, "--version").stdout.decode("utf-8", "replace")
    assert __version__ in out, out


def test_zipapp_demo_reads_its_packaged_cases(tmp_path):
    """The demo loads its cases through importlib.resources; inside a zip
    there is no filesystem path to fall back to."""
    proc = _run(_build(tmp_path), "demo")
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out + proc.stderr.decode("utf-8", "replace")
    assert "7/7 tampering cases blocked" in out, out


def test_zipapp_checks_a_real_repository(tmp_path):
    """End to end on an actual git history: this repository's own last commit."""
    proc = _run(_build(tmp_path), "check", "HEAD~1..HEAD", "--repo", str(ROOT), "--format", "json")
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
    import json

    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["verdict"] in ("pass", "block")


def test_no_runtime_dependencies_so_the_single_file_can_exist():
    """The zipapp bundles `src/` and nothing else. A runtime dependency would
    make it a broken file that only fails on someone else's machine."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as fh:
        deps = tomllib.load(fh)["project"].get("dependencies") or []
    assert deps == [], f"runtime dependencies would break the single-file build: {deps}"
