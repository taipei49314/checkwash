# Verdict gate inputs (#201)

Inputs of the previous-release verdict gate, `tools/verdict_gate.py`, run by
`.github/workflows/verdict-gate.yml`. The tool's module docstring is the
contract for every file here.

| file | what it holds | who edits it |
|---|---|---|
| `cases/{i196,i197,i198,i199}/<row>.vgcase` | the 149 T1 cases, transcribed from the #196-#199 probe matrices | a reviewed PR; inputs only, never an expected verdict |
| `labels.toml` | `block`, `pass` or `undecided` for every T1 case, each with its source | a label changes only by maintainer ruling (`AGENTS.md` rule 2) |
| `baseline.toml` | the pins: baseline engine, canary pair, `[t3.cases]`, and later `baseline_blocked` and `[canary] block_to_pass` | a reviewed PR (rotation after a release) |

The acceptance list, `tests/gates/verdict_gate_accepted.toml`, is not here: it
is maintainer-only (`tests/gates/**`, #201 Decision 1).

## Case files

A case id is its path without the extension (`i197/A5`); its `input_sha256` is
the sha256 of the file bytes, so any edit retires the acceptance entries that
name it. A case is a base commit plus one head commit: `base:` sections build
the base tree, `head:`, `delete:`, `rename:` and `rename-same:` sections build
HEAD. `meta` records the issue, row, probe and source, and, as `#` comments,
how that one case differs from its in-process probe. Two differences hold
for whole sets and are not repeated in each case: the CLI always wires the
head and root readers over the real head tree (the #196 and #198 probes, and
#197 except A10, passed none), and the CLI sees changes in git's path order
(different from the probe's order in #197 C5 and C5ctl and #199 P3 and P5).
One row changes verdict because of this: the first hosted run (36983670433)
saw #197 B7 block on v0.5.0, where the in-process probe passed it. Git does
not pair B7's rename-with-edit, so the CLI sees a delete plus an add, and
deleting a test under `.github/workflows/` escalates to high. The canary set
is therefore 67 rows, not the matrices' 68, and B7 needs no acceptance entry.
`options` sets `today` (every case: `2026-10-02`) and, for the #196 S rows,
`task = "TASK.md"`.

Inspect without running an engine:

```
python tools/verdict_gate.py cases --cases tests/verdict_gate/cases --labels tests/verdict_gate/labels.toml
python tools/verdict_gate.py materialize --case tests/verdict_gate/cases/i197/A5.vgcase --out /tmp/a5
```

`tests/test_verdict_gate_cases.py` parses every case, the labels and the pins
on every CI leg (no git, no engine).

## Reading a run

The job summary and the `verdict-gate-receipt-<attempt>` artifact hold the
receipt: engine identities (sha256, size, version, commit, controls), one row
per case (`baseline -> candidate` transition, canary transition, label,
acceptance entry), the failures, the reported-only rows, and, where an entry
or a pin is missing or has drifted, ready-to-paste TOML. The gate never writes
an entry or a pin. `python tools/verdict_gate.py propose --receipt <json>`
prints that TOML again from a downloaded receipt.
