"""The informed tamper corpus, as a gate rather than as a one-off measurement.

40 cases from the 2026-08-13 informed adversarial run. Twelve block; twenty-eight
escape, and each escape stands only because THREATMODEL 91 admits the hole is
open. When that row closes, this gate is what stops it closing on paper only.

The provenance half — production byte-identical, `pytest` red before and green
after — was established once by `benchmarks/tamper/verify.py` and is not re-run
here: eighty pytest subprocesses do not belong in the unit suite. What is
replayed on every push is greenwash's verdict, which is what regresses.

Modelled on `test_recorded_arms.py`, and for the same reason: a measurement that
runs when someone remembers is a measurement that stops running.
"""

import json
import pathlib

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.pyenv import known_baseline

import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
TAMPER = ROOT / "benchmarks" / "tamper"
TODAY = datetime.date(2026, 1, 1)


def _expected() -> dict:
    return json.loads((TAMPER / "expected.json").read_text(encoding="utf-8"))["cases"]


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def _verdict(case: pathlib.Path) -> tuple[str, list[str]]:
    before_dir, after_dir = case / "before", case / "after"
    paths = sorted(
        {_rel(p, before_dir) for p in before_dir.rglob("*.py")}
        | {_rel(p, after_dir) for p in after_dir.rglob("*.py")}
    )
    changes = []
    for path in paths:
        b, a = before_dir / path, after_dir / path
        changes.append(
            FileChange(
                path=path,
                status=("modified" if b.exists() and a.exists()
                        else "added" if a.exists() else "deleted"),
                before=b.read_bytes() if b.exists() else None,
                after=a.read_bytes() if a.exists() else None,
            )
        )
    head = {f"src/{_rel(p, case / 'src')}": p.read_bytes()
            for p in (case / "src").rglob("*.py")}
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
    return {name: _verdict(TAMPER / "cases" / name) for name in _expected()}


def test_every_tamper_case_still_behaves(replayed):
    problems = []
    for name, spec in _expected().items():
        verdict, rules = replayed[name]
        if spec["verdict"] == "block":
            if verdict != "block":
                problems.append(
                    f"{name}: REGRESSION — recorded as blocked, now {verdict} "
                    f"({', '.join(rules) or 'no findings'})"
                )
        elif verdict == "block":
            problems.append(
                f"{name}: recorded as an authorised escape and now blocks ({', '.join(rules)}). "
                "Good news — update expected.json, and close THREATMODEL 91 when the family is done."
            )
    assert not problems, "tamper-corpus regressions:\n  " + "\n  ".join(problems)


def test_the_table_covers_every_case_on_disk():
    on_disk = {p.name for p in (TAMPER / "cases").iterdir() if p.is_dir()}
    assert on_disk == set(_expected()), (
        f"cases not in expected.json: {sorted(on_disk - set(_expected()))}; "
        f"listed but missing: {sorted(set(_expected()) - on_disk)}"
    )


def test_escapes_are_authorised_by_an_open_row():
    """An escape may only stand on a row that admits it is open."""
    text = (ROOT / "THREATMODEL.md").read_text(encoding="utf-8")
    status = {}
    for line in text.split("\n"):
        if line.startswith("| "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3:
                status.setdefault(cells[0], cells[2])
    problems = []
    for name, spec in _expected().items():
        if spec["verdict"] == "block":
            continue
        row = spec.get("threatmodel_row")
        if row not in status:
            problems.append(f"{name}: THREATMODEL row {row!r} does not exist")
        elif "closed" in status[row].lower():
            problems.append(f"{name}: authorised by row {row}, which is marked closed")
        if not spec.get("why"):
            problems.append(f"{name}: no reason recorded")
    assert not problems, "\n  ".join(problems)


def test_the_corpus_is_large_enough_to_mean_something():
    assert len(_expected()) >= 40, "the tamper corpus shrank"
