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
in `src/checkwash/demo_cases/` and are loaded exactly the way a pipx install
loads them.
"""

import os
import subprocess
import sys
import tomllib
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build(tmp_path: Path) -> Path:
    target = tmp_path / "checkwash.pyz"
    zipapp.create_archive(
        ROOT / "src",
        target=target,
        main="checkwash.zipapp_entry:run",
        compressed=True,
    )
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
    with open(ROOT / "pyproject.toml", "rb") as source:
        __version__ = tomllib.load(source)["project"]["version"]
    proc = _run(pyz, "--version")
    out = proc.stdout.decode("utf-8", "replace")
    assert __version__ in out, out
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert out.strip() == f"checkwash {__version__}", out

    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'python -m zipapp src -m "checkwash.zipapp_entry:run"' in release
    assert "python tools/qualify_zipapp.py dist/checkwash.pyz" in release


def test_zipapp_demo_reads_its_packaged_cases(tmp_path):
    """The demo loads its cases through importlib.resources; inside a zip
    there is no filesystem path to fall back to.

    The expected count is derived from the packaged cases rather than written
    here as a literal. A hardcoded "7/7" needs hand-editing every time a demo
    case is added, and — more to the point — it passes just as happily if the
    zip silently ships fewer cases than the source tree has, which is exactly
    the failure this test exists to catch. Counting the cases independently
    and requiring the demo to block all of them fails in that case.
    """
    from checkwash.cases import parse_case
    from checkwash.demo import _load_cases

    # The floor on how many cases must exist is asserted next door in
    # test_demo_command.py; repeating it here would be a second place to
    # update and buys nothing.
    tampering = [name for name, text in _load_cases() if parse_case(text).expect]

    proc = _run(_build(tmp_path), "demo")
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out + proc.stderr.decode("utf-8", "replace")
    assert f"{len(tampering)}/{len(tampering)} tampering cases blocked" in out, out


def test_zipapp_checks_a_real_repository(tmp_path):
    """End to end on an actual git history: this repository's own last commit."""
    proc = _run(_build(tmp_path), "check", "HEAD~1..HEAD", "--repo", str(ROOT), "--format", "json")
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
    import json

    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["verdict"] in ("pass", "block")


def test_zipapp_preserves_process_exit_contract(tmp_path):
    """The generated top-level entry point must propagate CLI exits 0/1/2."""
    pyz = _build(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "qualify_zipapp.py"), str(pyz)],
        capture_output=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert proc.returncode == 0, (
        proc.stdout.decode("utf-8", "replace")
        + proc.stderr.decode("utf-8", "replace")
    )


def test_no_runtime_dependencies_so_the_single_file_can_exist():
    """The zipapp bundles `src/` and nothing else. A runtime dependency would
    make it a broken file that only fails on someone else's machine."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as fh:
        deps = tomllib.load(fh)["project"].get("dependencies") or []
    assert deps == [], f"runtime dependencies would break the single-file build: {deps}"
