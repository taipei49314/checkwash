"""STATE.md's authoritative table must match what the harnesses say.

On 2026-08-04 the owner caught STATE.md carrying three generations of
"current" numbers at once — the headline said one thing, "The number that
matters" another, "Where we are" still described v0.1.2. Every paragraph had
historical basis; the document as a whole could not be true. That is the
exact claim drift greenwash exists to catch, happening in its own takeover
file.

The fix is structural: STATE.md now has exactly one authoritative table, and
this test recomputes every row from its source of truth. Prose can narrate
history; the table cannot drift.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _table() -> dict[str, str]:
    text = (ROOT / "STATE.md").read_text(encoding="utf-8")
    marker = "## The numbers that matter right now"
    assert marker in text, "STATE.md lost its authoritative table heading"
    section = text.split(marker, 1)[1]
    rows: dict[str, str] = {}
    for line in section.split("\n"):
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", line)
        if m and m.group(1) != "authoritative number" and not set(m.group(1)) <= {"-"}:
            rows[m.group(1)] = m.group(2)
        if line.startswith("## ") and marker not in line:
            break
    assert rows, "STATE.md's authoritative table is empty or unparseable"
    return rows


def _sweeps() -> tuple[int, int, int]:
    total = blocked = opaque = 0
    for p in sorted((ROOT / "benchmarks" / "sweeps").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        total += d["commits_analysed"]
        blocked += d["commits_blocked"]
        opaque += d["commits_with_opaque_prod_change"]
    return total, blocked, opaque


def test_version_row_matches_package():
    from greenwash import __version__

    assert _table()["version"] == f"v{__version__}"


def test_detector_row_matches_registry():
    from greenwash.detectors import REGISTRY

    assert int(_table()["detectors"]) == len(REGISTRY)


def test_block_rate_row_matches_sweeps():
    total, blocked, _ = _sweeps()
    want = f"{blocked}/{total} = {blocked / total:.2%}"
    assert _table()["human-commit block rate"] == want


def test_opaque_row_matches_sweeps():
    total, _, opaque = _sweeps()
    want = f"{opaque}/{total} = {opaque / total:.2%}"
    assert _table()["opaque exemption share"] == want


def test_split_rows_match_adjudication():
    adj = json.loads(
        (ROOT / "benchmarks" / "adjudication-2026-08-26b.json").read_text(encoding="utf-8")
    )
    total, blocked, _ = _sweeps()
    cats: dict[str, int] = {}
    for v in adj["verdicts"]:
        cats[v["category"]] = cats.get(v["category"], 0) + 1
    assert sum(cats.values()) == blocked, "adjudication describes a different population"
    fp, sc = cats.get("false_positive", 0), cats.get("spec_correct", 0)
    table = _table()
    assert table["adjudicated false positive"] == f"{fp}/{total} = {fp / total:.2%}"
    assert table["legitimate policy block"] == f"{sc}/{total} = {sc / total:.2%}"


def test_decoy_row_matches_recorded_arm():
    arm = json.loads(
        (ROOT / "benchmarks" / "decoy" / "arm-adversarial-2026-07-30.json").read_text(
            encoding="utf-8"
        )
    )
    caught = sum(
        1
        for r in arm["runs"]
        if r["suite_passing"] and r["greenwash_verdict"] == "block"
    )
    n = len(arm["runs"])
    assert _table()["classic adversarial decoys blocked"] == f"{caught}/{n}"


def test_threatmodel_floor_matches_adjudicated_rate():
    adj = json.loads(
        (ROOT / "benchmarks" / "adjudication-2026-08-26b.json").read_text(encoding="utf-8")
    )
    total, _, _ = _sweeps()
    fp = sum(1 for v in adj["verdicts"] if v["category"] == "false_positive")
    want = f"~{fp / total:.2%}"
    text = (ROOT / "THREATMODEL.md").read_text(encoding="utf-8")
    m = re.search(r"false-positive floor(?: of this design on this corpus)? is (~[\d.]+%)", text)
    assert m, "THREATMODEL.md no longer states the floor"
    assert m.group(1) == want, (
        f"THREATMODEL.md states the floor as {m.group(1)}, the adjudication says {want}"
    )


def test_undated_sections_carry_no_stale_numbers():
    """A section that does not say when it was written must be current.

    The 2026-08-04 fix gave STATE.md one authoritative table and a test for
    it, and that was not enough: `## Known and unfixed, top of the next
    round` went on saying "still unfixed and still measured: 7.2%" three
    rounds after it became 2.5%, and `## Later` still listed the inter-rater
    adjudication as to-do a day after it shipped. Both were undated,
    present-tense, and wrong.

    So the file's own rule — narrate history under a dated heading, state the
    present only in the table — is now enforced rather than requested. A
    heading with a date may say anything; an undated one may only use numbers
    that are still true.
    """
    total, blocked, opaque = _sweeps()
    live = {f"{blocked / total:.2%}", f"{opaque / total:.2%}", f"{opaque / total:.1%}"}
    adj = json.loads(
        (ROOT / "benchmarks" / "adjudication-2026-08-26b.json").read_text(encoding="utf-8")
    )
    for cat in ("false_positive", "spec_correct"):
        n = sum(1 for v in adj["verdicts"] if v["category"] == cat)
        live.add(f"{n / total:.2%}")

    text = (ROOT / "STATE.md").read_text(encoding="utf-8")
    heading, dated, stale = "(top of file)", True, []
    for lineno, line in enumerate(text.split("\n"), 1):
        if line.startswith("#"):
            heading = line
            dated = bool(re.search(r"20\d\d-\d\d-\d\d", line)) or "authoritative" in line
            continue
        if dated:
            continue
        for pct in re.findall(r"\d+\.\d+%", line):
            if pct not in live:
                stale.append(f"  STATE.md:{lineno} under `{heading.strip('# ')}` says {pct}")
    assert not stale, (
        "undated sections state numbers that are no longer true — date the heading if the "
        "paragraph is history, or fix the number:\n" + "\n".join(stale)
    )


def test_readme_headline_numbers_match_the_harnesses():
    """The README is the document most people read, so it gets the same pin.

    STATE.md's table has been machine-checked since 2026-08-04; the README's
    four headline numbers were still kept in step by hand, which is the
    process that produced every drift this project has caught. Each is
    recomputed from the sweeps and the adjudication, not compared to a stored
    copy of itself.
    """
    total, blocked, opaque = _sweeps()
    adj = json.loads(
        (ROOT / "benchmarks" / "adjudication-2026-08-26b.json").read_text(encoding="utf-8")
    )
    fp = sum(1 for v in adj["verdicts"] if v["category"] == "false_positive")
    sc = sum(1 for v in adj["verdicts"] if v["category"] == "spec_correct")
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    expected = {
        "block rate": f"{blocked} / {total} = {blocked / total:.2%}",
        "false positives": f"**{fp} false positives ({fp / total:.2%})**",
        "policy blocks": f"{sc} legitimate\n  policy blocks ({sc / total:.2%})",
        "opaque share": f"**{opaque / total:.2%} of the corpus ({opaque}/{total}) never got a real analysis**",
    }
    missing = [f"{name}: expected README to contain {want!r}" for name, want in expected.items()
               if want not in text]
    assert not missing, "README numbers drifted from the harnesses:\n" + "\n".join(missing)


def test_results_reports_the_adjudication_it_actually_had():
    """RESULTS.md must not disagree with the adjudication file it summarises.

    It did, for four days and five releases. The paragraph asserting "judged
    once, with no second opinion and no inter-rater agreement measured" was a
    fixed string inside `make_results.py`, so regenerating the document —
    the whole point of generating it — re-emitted the contradiction, while
    README, benchmarks/README and STATE all published three raters and a
    Fleiss' kappa. STATE went further and claimed this paragraph had already
    been corrected: a false claim about having fixed a false claim.

    A document generated so it cannot drift is worth nothing when the
    generator is where the drift lives.
    """
    adj = json.loads(
        (ROOT / "benchmarks" / "adjudication-2026-08-26b.json").read_text(encoding="utf-8")
    )
    results = (ROOT / "benchmarks" / "RESULTS.md").read_text(encoding="utf-8")
    ir = adj.get("inter_rater")
    if not (isinstance(ir, dict) and ir.get("raters", 1) > 1):
        assert "no inter-rater agreement measured" in results
        return
    assert "no inter-rater agreement measured" not in results, (
        "RESULTS.md still apologises for a single-pass adjudication that the "
        "adjudication file says had %d raters" % ir["raters"]
    )
    assert f"judged {ir['raters']} times" in results
    assert f"{ir['fleiss_kappa']:.3f}" in results, (
        f"RESULTS.md does not state the measured Fleiss' kappa {ir['fleiss_kappa']}"
    )


def test_failures_ledger_is_current():
    """`benchmarks/FAILURES.md` must be what its generator produces today.

    It is the one page that collects every known way this tool is wrong, and
    a stale version of that page is worse than not having it: it would let a
    row go open in THREATMODEL while the summary still called it closed.
    Regenerate with `python benchmarks/make_failures.py`.
    """
    import io
    import runpy
    import contextlib

    committed = (ROOT / "benchmarks" / "FAILURES.md").read_text(encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(ROOT / "benchmarks" / "make_failures.py"), run_name="__main__")
    regenerated = (ROOT / "benchmarks" / "FAILURES.md").read_text(encoding="utf-8")
    if committed != regenerated:
        (ROOT / "benchmarks" / "FAILURES.md").write_text(committed, encoding="utf-8", newline="\n")
    assert committed == regenerated, (
        "benchmarks/FAILURES.md is stale — run `python benchmarks/make_failures.py`"
    )
