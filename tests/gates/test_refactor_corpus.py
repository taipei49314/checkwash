"""The legitimate-refactor corpus, as a gate.

30 refactors that keep an oracle which still catches the bug. Twenty are false
positives today (THREATMODEL 92). This gate does two things a one-off
measurement cannot: it fails if one of the ten currently-silent cases starts
blocking, and it fails if a false positive is quietly fixed without the table
being updated — so the number in the README cannot drift from the behaviour.

The provenance half — four pytest runs proving both sides catch the bug — was
established once by `benchmarks/refactors/verify.py` and is not repeated here;
120 pytest subprocesses do not belong in the unit suite. What runs on every
push is greenwash's verdict, which is what moves.
"""

import datetime
import json
import pathlib

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.pyenv import known_baseline

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = ROOT / "benchmarks" / "refactors"
TODAY = datetime.date(2026, 1, 1)


def _expected() -> dict:
    return json.loads((CORPUS / "expected.json").read_text(encoding="utf-8"))["cases"]


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def _verdict(case: pathlib.Path):
    before_root, after_root = case / "BEFORE", case / "AFTER"
    src = case / "PROD-GOOD" / "src"
    paths = sorted(
        {_rel(p, before_root) for p in before_root.rglob("*.py")}
        | {_rel(p, after_root) for p in after_root.rglob("*.py")}
    )
    changes = []
    for path in paths:
        b, a = before_root / path, after_root / path
        changes.append(
            FileChange(
                path=path,
                status=("modified" if b.exists() and a.exists()
                        else "added" if a.exists() else "deleted"),
                before=b.read_bytes() if b.exists() else None,
                after=a.read_bytes() if a.exists() else None,
            )
        )
    head = {f"src/{_rel(p, src)}": p.read_bytes() for p in src.rglob("*.py")}
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY,
        known_modules=known_baseline() | {"app"},  # the corpora ship app.* by construction
        head_reader=head.get,
        head_searcher=lambda needles: [
            p for p, d in sorted(head.items()) if any(n.encode() in d for n in needles)
        ],
    )
    return verdict, sorted({f.rule for f in findings if not f.allowlisted})


@pytest.fixture(scope="module")
def replayed() -> dict:
    return {name: _verdict(CORPUS / "cases" / name) for name in _expected()}


def test_no_silent_refactor_starts_blocking(replayed):
    """The ten that pass must keep passing. These are the regression guard."""
    problems = []
    for name, spec in _expected().items():
        if spec["blocks"]:
            continue
        verdict, rules = replayed[name]
        if verdict == "block":
            problems.append(f"{name}: NEW false positive ({', '.join(rules)})")
    assert not problems, "honest refactors that started blocking:\n  " + "\n  ".join(problems)


def test_fixed_false_positives_are_recorded(replayed):
    """A false positive that gets fixed must be recorded, not left claimed."""
    stale = []
    for name, spec in _expected().items():
        if not spec["blocks"]:
            continue
        verdict, _rules = replayed[name]
        if verdict != "block":
            stale.append(name)
    assert not stale, (
        "these no longer block — good news, but expected.json and the README's "
        f"20/30 still say they do: {stale}"
    )


def test_the_table_covers_every_case_on_disk():
    on_disk = {p.name for p in (CORPUS / "cases").iterdir() if p.is_dir()}
    assert on_disk == set(_expected()), (
        f"cases not in expected.json: {sorted(on_disk - set(_expected()))}; "
        f"listed but missing: {sorted(set(_expected()) - on_disk)}"
    )
