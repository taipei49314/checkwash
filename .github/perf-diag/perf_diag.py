"""Temporary diagnostic, not for merge: relative cost of the perf gate's two shapes across commits.

`tests/gates/test_perf.py` fails on main's push run at adea2350 (integration
batch 2) on Windows 3.12 and 3.13, while the same src tree passed on its PR
run. CI prints a median only when the gate fails, so passing runs say
nothing about how the engine's cost moved. This script extracts `src/` and
`tests/gates/test_perf.py` of each commit below with `git archive` and, in a
fresh process per commit, times `analyze` on exactly the gate's inputs with
the gate's own helpers (`_test_module`, `_median_elapsed`), after one
untimed warm-up call. Commits are measured in interleaved rounds, the order
reversed every other round, and each round's value is divided by batch 1's
value in the same round (a paired ratio).

What it measures: one engine alone in an idle process. The gate in CI runs
inside `pytest -n 2` beside a second busy worker, so these absolute numbers
are NOT comparable to the gate's budgets; only the ratios between commits
are the result. Two pairs of commits have identical src trees (A/A
controls); a step between commits smaller than their difference cannot be
attributed to code.

Nothing here is a test. The engine has no runtime dependencies (D-001);
pytest is installed only because the gate module imports it.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import statistics
import subprocess
import sys
import tarfile
import tempfile

COMMITS = [
    ("v0.8.0", "f02b5d8a07fa39ee1898881f66c571eb164cb11c"),
    ("main #507 (A/A pair 1)", "1714d293dcad7f8500cfc482f09d373f4bdd4ec6"),
    ("main #526 (A/A pair 1)", "f324eb2c76fabb8fd863c98cbb02d48adbf1be9f"),
    ("batch 1 (main 0eff0e52)", "0eff0e522427470fb1d0821377316793ed37cebe"),
    ("b2 +#509", "eb24d86143fbf1bc447735e7b7bfb1d1874ebdc2"),
    ("b2 +#520", "4396a0446d61c4f7afb58b3d182116415ef02163"),
    ("b2 +#528", "1aebd19611cca91f23fd5ece80357823be7e61a1"),
    ("b2 +#524", "d6d9d092f0b64a6d7a2d487ca0fb8a9dc0bfdf98"),
    ("b2 +#525", "3767b7dd3f00d5a66fc42c70c3735a2a338d9f3c"),
    ("b2 +#527", "3e37a7016401a84ddd1cb46bd98e1d82a317f0db"),
    ("b2 +#522", "65282aa8be09b338e188ba465bc0257333dacee7"),
    ("b2 +#531 (A/A pair 2)", "737f13b8d3a6180dc14467b062d7d55d1f9430e1"),
    ("main adea2350 (A/A pair 2)", "adea23509647d227881b2d798b7540b4726a80b8"),
    ("#540 batch 3", "d271b87c42e37f9a28b0126f2cee1dbceebc5356"),
    ("#537 (#512)", "41f12c0d0ff6a6aa0e8a89f63598f4d6e552f740"),
    ("#536 (#455)", "2a6ee2f94a50f5a9455d462b353ad2c024805017"),
    ("#534 (#454 d)", "87f5b887c5c4ed055999d4bdf5df84d88ee76692"),
    ("#538 (#484)", "fd00ec1271432b69bd094302a88d16e5056e7371"),
    ("#535 (#499)", "d673d5bc172dfefd408eb154a3bc8a6da090e94e"),
    ("#539 (#480)", "6a75ca59080d4df91b9b2fd57b3421d04e870a53"),
]
ROUNDS = 5
BASELINE = "0eff0e522427470fb1d0821377316793ed37cebe"
BENCH_TIMEOUT_S = 600

BENCH = r'''
import importlib.util
import json
import pathlib
import sys

root = sys.argv[1]
spec = importlib.util.spec_from_file_location("perf_gate", root + "/tests/gates/test_perf.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
import checkwash
from checkwash.engine import FileChange

assert pathlib.Path(root).name in checkwash.__file__, checkwash.__file__  # this commit's engine, not another
many = [
    FileChange(f"tests/test_mod_{i:03d}.py", "modified",
               gate._test_module(4, weaken=False), gate._test_module(4, weaken=(i % 10 == 0)))
    for i in range(500)
]
large = [FileChange("tests/test_big.py", "modified",
                    gate._test_module(600, weaken=False), gate._test_module(600, weaken=True))]
# Untimed warm-up: the gate runs in an already-warm pytest worker.
_ir, many_findings, many_verdict = gate.analyze(many, gate.Config(), gate.Contract(), [], gate.TODAY)
_ir, large_findings, large_verdict = gate.analyze(large, gate.Config(), gate.Contract(), [], gate.TODAY)
many_s, _ = gate._median_elapsed(many)
large_s, _ = gate._median_elapsed(large)
print(json.dumps({
    "many_files": many_s, "large_diff": large_s,
    "work": [len(many_findings), str(many_verdict), len(large_findings), str(large_verdict)],
}))
'''


def extract(sha: str, dest: pathlib.Path) -> None:
    data = subprocess.run(
        ["git", "archive", "--format=tar", sha, "src", "tests/gates/test_perf.py"],
        check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(dest, filter="data")


def run_bench(bench: pathlib.Path, root: pathlib.Path, work: pathlib.Path) -> dict:
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    env.pop("PYTHONUTF8", None)  # as in CI's pytest step
    try:
        proc = subprocess.run(
            [sys.executable, str(bench), str(root)], env=env, capture_output=True,
            encoding="utf-8", errors="replace", cwd=str(work), timeout=BENCH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {BENCH_TIMEOUT_S}s"}
    if proc.returncode != 0:
        return {"error": proc.stderr[-1500:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "no result line: " + proc.stdout[-500:]}


def summarize(samples: dict[str, list[dict]], unavailable: dict[str, str]) -> dict:
    base = {}
    for index, sample in enumerate(samples[BASELINE]):
        base[index] = sample
    rows = []
    base_work = next((s["work"] for s in samples[BASELINE] if "work" in s), None)
    for label, sha in COMMITS:
        row = {"label": label, "sha": sha}
        if sha in unavailable:
            row["unavailable"] = unavailable[sha]
            rows.append(row)
            continue
        for key in ("many_files", "large_diff"):
            values = [s[key] for s in samples[sha] if key in s]
            ratios = [
                s[key] / base[i][key]
                for i, s in enumerate(samples[sha])
                if key in s and i in base and key in base[i] and base[i][key]
            ]
            row[key] = {
                "median_s": statistics.median(values) if values else None,
                "min_s": min(values) if values else None,
                "max_s": max(values) if values else None,
                "ratio_median": statistics.median(ratios) if ratios else None,
                "ratio_min": min(ratios) if ratios else None,
                "ratio_max": max(ratios) if ratios else None,
            }
        works = {json.dumps(s["work"]) for s in samples[sha] if "work" in s}
        row["work"] = sorted(works)
        row["same_work_as_batch1"] = base_work is not None and works == {json.dumps(base_work)}
        row["errors"] = [s["error"] for s in samples[sha] if "error" in s]
        rows.append(row)
    return {"rows": rows, "samples": samples}


def table(result: dict) -> str:
    def fmt(value, digits=2):
        return "-" if value is None else f"{value:.{digits}f}"

    lines = [
        f"### perf gate shapes, relative to batch 1: {result['runner_os']}, Python {result['python_short']}",
        "",
        f"{result['rounds']} interleaved rounds; each value is the gate's own median of three runs after a warm-up,",
        "in one idle process. Absolute seconds are NOT comparable to the CI budgets (the gate runs beside a",
        "second pytest-xdist worker); read the ratio columns. The A/A pairs have identical src trees: a step",
        "smaller than their gap is noise.",
        "",
        "| commit | sha | many files: ratio median (min-max) | s | large diff: ratio median (min-max) | s | same work |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        if "unavailable" in row:
            lines.append(f"| {row['label']} | `{row['sha'][:8]}` | unavailable | | | | |")
            continue
        cells = []
        for key in ("many_files", "large_diff"):
            m = row[key]
            cells.append(f"{fmt(m['ratio_median'], 3)} ({fmt(m['ratio_min'], 3)}-{fmt(m['ratio_max'], 3)})")
            cells.append(fmt(m["median_s"]))
        flag = "yes" if row["same_work_as_batch1"] else "NO " + "; ".join(row["work"])
        if row["errors"]:
            flag += f"; {len(row['errors'])} error(s)"
        lines.append(f"| {row['label']} | `{row['sha'][:8]}` | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {flag} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    out = pathlib.Path(sys.argv[1])
    work = pathlib.Path(tempfile.mkdtemp(prefix="perf-diag-"))
    bench = work / "bench_one.py"
    bench.write_text(BENCH, encoding="utf-8")
    roots: dict[str, pathlib.Path] = {}
    unavailable: dict[str, str] = {}
    for _label, sha in COMMITS:
        root = work / sha[:12]
        root.mkdir()
        try:
            extract(sha, root)
            roots[sha] = root
        except (subprocess.CalledProcessError, tarfile.TarError, OSError) as exc:
            unavailable[sha] = f"{type(exc).__name__}: {exc}"
    samples: dict[str, list[dict]] = {sha: [] for sha in roots}
    result = {
        "runner_os": os.environ.get("RUNNER_OS"), "python": sys.version,
        "python_short": sys.version.split()[0], "rounds": ROUNDS,
        "note": "isolated single process; ratios to batch 1 are the result, not the absolute seconds",
    }
    present = [(label, sha) for label, sha in COMMITS if sha in roots]
    for round_no in range(ROUNDS):
        order = present if round_no % 2 == 0 else list(reversed(present))
        for label, sha in order:
            samples[sha].append(run_bench(bench, roots[sha], work))
            print(f"round {round_no + 1} {label} {sha[:8]}: {samples[sha][-1]}", flush=True)
        for sha in unavailable:
            samples.setdefault(sha, [])
        result.update(summarize(samples, unavailable) if BASELINE in roots else {"rows": [], "samples": samples})
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text = table(result) if result.get("rows") else "baseline unavailable\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
