# Compare harness — greenwash vs swarm-orchestrator

Head-to-head on the decoy corpus, both tools with **no LLM judge**.
Published numbers live in [COMPARISON.md](COMPARISON.md) (run
2026-07-31). This directory is how to re-run them. It does not invent
a new score.

**The corpus is Python.** That is greenwash's first-class ecosystem
and swarm's secondary one. T3.1 added a JS/TS *oracle scan* to
greenwash; this harness still does not measure swarm on JavaScript,
and it still does not measure greenwash's JS frontend. A re-run that
quietly dropped that caveat would be a different comparison.

## Prerequisites

1. This greenwash checkout, with the package importable
   (`pip install -e .` or `python -m greenwash`).
2. A swarm-orchestrator checkout whose CLI is a JS file
   (`swarm-cli-js` in the command below). This clone does not vendor
   it.
3. Node, to run that CLI.

If any path is missing, `run.py` exits 2 and names it. It does not
print a comparison.

## Reproduce

```bash
# 1. Materialize the two decoy worktrees (12 tasks each, diffs applied)
python benchmarks/compare/prepare.py /tmp/gw-compare

# 2. Point at swarm's CLI (path will differ on your machine)
python benchmarks/compare/run.py \
    "$(command -v python)" \
    /path/to/swarm-orchestrator/cli.js \
    /tmp/gw-compare/arm-b \
    /tmp/gw-compare/arm-a \
    /tmp/gw-compare/out.json
```

`arm-b` is the 2026-07-30 adversarial arm (cheats). `arm-a` is the
natural arm (honest fixes). Those are the same 24 diffs COMPARISON.md
reports. `prepare.py` drops later probe tasks that `make_tasks.py`
also materializes — they are recall measurements for greenwash
alone, and scoring them here would change the comparison.

`run.py` writes the per-case JSON and prints the summary. Compare
that summary to COMPARISON.md; do not edit COMPARISON.md from a
partial run.

## If a clone is missing

- No decoy worktrees: run `prepare.py`. It fails clearly if
  `benchmarks/decoy/make_tasks.py` cannot materialize the twelve
  repos.
- No swarm CLI: this harness cannot run. Install swarm-orchestrator
  yourself; this project does not pin or vendor it.
- `run.py` given four paths instead of five, or a path that does not
  exist: exit 2, usage on stderr.

## What a re-run is allowed to change

The methodology limits in COMPARISON.md stay. A new date and new
tool versions belong in a new paragraph, not as a silent rewrite of
the 2026-07-31 table.
