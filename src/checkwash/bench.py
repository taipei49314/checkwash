"""`checkwash bench` — reproduce the published numbers from this checkout.

The decoy, tamper and refactor corpora live in this clone. The false-positive
corpus is six third-party repositories this clone cannot contain. This
command runs the in-clone sanity (demo), points at benchmarks/README.md for
the rest, and fails closed when the sweep clones are missing instead of
printing a number nobody can check.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from checkwash.demo import run as run_demo

# Official remotes for the six-repo false-positive corpus. Names match
# benchmarks/sweeps/<name>.json. The SHAs come from those files, not here.
CORPUS_REMOTES = {
    "attrs": "https://github.com/python-attrs/attrs",
    "click": "https://github.com/pallets/click",
    "flask": "https://github.com/pallets/flask",
    "httpx": "https://github.com/encode/httpx",
    "rich": "https://github.com/Textualize/rich",
    "starlette": "https://github.com/encode/starlette",
}


@dataclass
class CloneStatus:
    name: str
    path: Path | None
    newest: str
    oldest: str
    present: bool
    pin_present: bool
    remote: str


@dataclass
class BenchReport:
    checkout: Path | None = None
    readme: Path | None = None
    demo_ok: bool = False
    demo_detail: str = ""
    decoy_ok: bool = False
    decoy_detail: str = ""
    tamper_ok: bool = False
    refactor_ok: bool = False
    clones: list[CloneStatus] = field(default_factory=list)
    missing_clones: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def find_checkout(start: str | Path) -> Path | None:
    """Walk up from start looking for this project's benchmarks tree."""
    cur = Path(start).resolve()
    candidates = [cur, *cur.parents]
    for path in candidates:
        readme = path / "benchmarks" / "README.md"
        sweeps = path / "benchmarks" / "sweeps"
        if readme.is_file() and sweeps.is_dir():
            return path
    return None


def corpus_root(explicit: str | None, checkout: Path) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("GREENWASH_CORPUS")
    if env:
        return Path(env)
    sibling = checkout.parent / "greenwash-corpus"
    if sibling.is_dir():
        return sibling
    return None


def _load_sweep_pins(checkout: Path) -> list[tuple[str, str, str]]:
    """(name, newest, oldest) from tracked sweep JSONs."""
    out: list[tuple[str, str, str]] = []
    sweeps = checkout / "benchmarks" / "sweeps"
    for path in sorted(sweeps.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        corpus = data.get("corpus") or {}
        newest = corpus.get("newest_commit") or ""
        oldest = corpus.get("oldest_commit") or ""
        out.append((path.stem, newest, oldest))
    return out


def _is_git_repo(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def _has_commit(repo: Path, sha: str) -> bool:
    if not sha:
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
    )
    return proc.returncode == 0


def inspect_clones(checkout: Path, root: Path | None) -> list[CloneStatus]:
    rows: list[CloneStatus] = []
    for name, newest, oldest in _load_sweep_pins(checkout):
        remote = CORPUS_REMOTES.get(name, "")
        clone = (root / name) if root is not None else None
        present = bool(clone is not None and _is_git_repo(clone))
        pin_ok = bool(present and newest and clone is not None and _has_commit(clone, newest))
        rows.append(
            CloneStatus(
                name=name,
                path=clone if present else None,
                newest=newest,
                oldest=oldest,
                present=present,
                pin_present=pin_ok,
                remote=remote,
            )
        )
    return rows


def _local_corpora(checkout: Path, report: BenchReport) -> None:
    decoy = checkout / "benchmarks" / "decoy"
    arms = sorted(decoy.glob("arm-*.json"))
    expected = decoy / "expected.json"
    if expected.is_file() and arms:
        report.decoy_ok = True
        report.decoy_detail = f"{len(arms)} recorded arms; replay via pytest tests/gates/test_recorded_arms.py"
    else:
        report.decoy_ok = False
        report.decoy_detail = "benchmarks/decoy/expected.json or arm-*.json missing"
        report.errors.append(report.decoy_detail)

    report.tamper_ok = (checkout / "benchmarks" / "tamper" / "expected.json").is_file()
    report.refactor_ok = (checkout / "benchmarks" / "refactors" / "expected.json").is_file()
    if not report.tamper_ok:
        report.errors.append("benchmarks/tamper/expected.json missing")
    if not report.refactor_ok:
        report.errors.append("benchmarks/refactors/expected.json missing")


def _run_demo(report: BenchReport) -> None:
    buf = io.StringIO()
    code = run_demo(stream=buf)
    text = buf.getvalue()
    if code == 0 and "UNEXPECTED" not in text:
        report.demo_ok = True
        report.demo_detail = "demo replayed; every packaged tampering case blocked"
    else:
        report.demo_ok = False
        report.demo_detail = "demo failed or reported UNEXPECTED"
        report.errors.append(report.demo_detail)


def collect(
    start: str | Path = ".",
    corpus: str | None = None,
    local_only: bool = False,
) -> BenchReport:
    report = BenchReport()
    checkout = find_checkout(start)
    report.checkout = checkout
    if checkout is None:
        report.errors.append(
            "not a greenwash checkout — clone https://github.com/taipei49314/greenwash "
            "and run `checkwash bench` from that tree (or pass --repo pointing at it)"
        )
        return report

    report.readme = checkout / "benchmarks" / "README.md"
    _local_corpora(checkout, report)
    _run_demo(report)

    if local_only:
        return report

    root = corpus_root(corpus, checkout)
    report.clones = inspect_clones(checkout, root)
    report.missing_clones = [
        c.name for c in report.clones if not c.present or not c.pin_present
    ]
    if not report.clones:
        report.errors.append("no tracked sweep JSONs under benchmarks/sweeps/")
    elif report.missing_clones:
        report.errors.append(
            "sweep clones missing or missing the pinned newest commit: "
            + ", ".join(report.missing_clones)
        )
    return report


def render(report: BenchReport, stream=None, local_only: bool = False) -> int:
    stream = stream or sys.stdout
    w = stream.write

    w("checkwash bench — reproduce the published numbers\n")
    w("=" * 56 + "\n\n")
    w("What this command can check lives in this clone. The 1800-commit\n")
    w("false-positive corpus does not. Full recipe: benchmarks/README.md\n")
    if report.readme:
        w(f"  {report.readme}\n")
    w("\n")

    if report.checkout is None:
        for err in report.errors:
            w(f"FAIL  {err}\n")
        w("\nsummary: not a checkwash checkout; nothing was reproduced.\n")
        return 2

    w(f"checkout: {report.checkout}\n")
    w(f"  demo:      {'ok' if report.demo_ok else 'FAIL'}  {report.demo_detail}\n")
    w(f"  decoy:     {'ok' if report.decoy_ok else 'FAIL'}  {report.decoy_detail}\n")
    w(f"  tamper:    {'ok' if report.tamper_ok else 'FAIL'}\n")
    w(f"  refactors: {'ok' if report.refactor_ok else 'FAIL'}\n")
    w("\n")
    w("In-clone reproduce (already gated in CI):\n")
    w("  pytest tests/gates/test_recorded_arms.py\n")
    w("  python benchmarks/tamper/verify.py\n")
    w("  python benchmarks/refactors/verify.py\n")
    w("\n")

    if local_only:
        w("--local: third-party sweep clones not required.\n")
        if report.errors:
            w("\n")
            for err in report.errors:
                w(f"FAIL  {err}\n")
            w("\nsummary: local reproduce incomplete.\n")
            return 2
        w("summary: local reproduce ok. Sweep clones skipped.\n")
        return 0

    w("False-positive corpus (six third-party clones; this tree cannot contain them):\n")
    if not report.clones:
        w("  no sweep pins found\n")
    for clone in report.clones:
        if clone.present and clone.pin_present:
            mark = "ok  "
            where = str(clone.path)
        elif clone.present:
            mark = "MISS"
            where = f"{clone.path} (pinned {clone.newest[:12]} not in this clone; fetch)"
        else:
            mark = "MISS"
            where = "not found"
        w(f"  {mark} {clone.name:10} {where}\n")
        if mark == "MISS" and clone.remote and clone.newest:
            w(f"       git clone {clone.remote} {clone.name}\n")
            w(f"       git -C {clone.name} checkout {clone.newest}\n")
            w(f"       checkwash sweep HEAD --limit 300 --repo {clone.name}\n")

    if report.missing_clones:
        w("\nSet GREENWASH_CORPUS or pass --corpus DIR (one subdir per repo name).\n")
        w("A sibling directory named greenwash-corpus is also accepted.\n")
        w("Then re-run `checkwash bench` or, to actually sweep:\n")
        w("  checkwash bench --corpus DIR --run-sweep\n")
        w("\nsummary: sweep clones missing; published 1800-commit numbers not reproduced.\n")
        return 2

    w("\nClones are present and contain the pinned newest commits.\n")
    w("This command does not re-sweep 1800 commits unless you pass --run-sweep.\n")
    w("Regenerate RESULTS.md with:\n")
    w("  python benchmarks/make_results.py benchmarks/sweeps\n")
    if report.errors:
        w("\n")
        for err in report.errors:
            w(f"FAIL  {err}\n")
        return 2
    w("\nsummary: checkout + sweep clones ready.\n")
    return 0


def _run_sweeps(report: BenchReport, stream) -> int:
    """Re-run the published sweep window on each clone. Slow; opt-in."""
    from checkwash.sweep import sweep

    if report.checkout is None or report.missing_clones:
        stream.write("error: --run-sweep requires every sweep clone and pin\n")
        return 2
    today = __import__("datetime").date.today()
    for clone in report.clones:
        assert clone.path is not None
        stream.write(f"sweeping {clone.name} ({clone.path}) ...\n")
        stream.flush()
        result = sweep(str(clone.path), "HEAD", 300, today, None)
        stream.write(
            f"  analysed={result.commits} blocked={result.blocked} "
            f"newest={result.corpus_newest[:12]}\n"
        )
    stream.write("re-sweep finished; compare against benchmarks/sweeps/*.json\n")
    return 0


def run(
    start: str = ".",
    corpus: str | None = None,
    local_only: bool = False,
    run_sweep: bool = False,
    stream=None,
) -> int:
    stream = stream or sys.stdout
    report = collect(start, corpus=corpus, local_only=local_only)
    code = render(report, stream=stream, local_only=local_only)
    if code != 0:
        return code
    if run_sweep and not local_only:
        return _run_sweeps(report, stream)
    return 0
