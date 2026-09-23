# Bounded JS/TS historical source replay

The manifest preselects 14 authentic changed test files from seven exact public
commits in Jest, Vitest and Node. The selection and source classifications were
written before running either CheckWash version. SHA256 hashes bind complete
before/after source files; no snippets, rewritten examples or generated mutations
stand in for those files. Full upstream sources are downloaded at replay time
and retained with the receipt, not redistributed in this repository.

This is a small diagnostic regression sample, not a representative false-positive
rate or a detection benchmark. Ten source changes are classified as preserving
by static patch and companion-source review. Four are descriptive controls:
two uncertain oracle rewrites, a mixed table-case change, and an explicit whole
test removal. Those four do not contribute to a preserving pass count. Upstream
test suites and buggy-production qualification were not run during selection.
No literal-spelling-only historical change was found in the bounded search;
scalar canonicalization remains covered by the independent synthetic inventory.

| IDs | Exact source commit | Reviewed source change |
| --- | --- | --- |
| J01–J05 | [Jest c53bdbca](https://github.com/jestjs/jest/commit/c53bdbca4c209526987e8097a9edc30515c49eff) | Type annotations, casts, fixture/local renames; also a corrected subject and a changed table scenario |
| V01 | [Vitest 3ccbcc45](https://github.com/vitest-dev/vitest/commit/3ccbcc45e2644f131321a5047b28335a909a52e2) | Remove a redundant digit class from a timestamp regex |
| V02–V05 | [Vitest 46be62c2](https://github.com/vitest-dev/vitest/commit/46be62c20791c764aaf99ef5e1da2b019dea9008) | Relocate browser helper values and hook calculations; also replace count checks with a snapshot |
| N01 | [Node 97a3a820](https://github.com/nodejs/node/commit/97a3a8204c7c0eb35fc6c11274a7aee5d2ea3ddc) | Use globalThis in timer tests |
| N02 | [Node 8c3e9bd9](https://github.com/nodejs/node/commit/8c3e9bd96706e3b21e7064c709d36ec584e817aa) | Replace immediate controller abort with an already-aborted signal |
| N03 | [Node 82fc59d4](https://github.com/nodejs/node/commit/82fc59d4cb9e830c27e0b1f5d36977adc450cedd) | Add cleanup hooks to nested coverage tests |
| N04 | [Node 9e6c526f](https://github.com/nodejs/node/commit/9e6c526f6c4e21b96f999869ceb265fb1891bf15) | URL refactors together with removal of a complete module-mocking test |

Each row is a single-file projection at the original repository path. It is not
the complete upstream commit, and its outcome is not a judgment about upstream
intent. Companion files support the source-review classification but are not
silently included as production changes in the replay. Multiple files from one
commit are correlated; report 14 file diffs and seven commits separately.

Run only on the authorized remote qualification host, after installing the exact
candidate into an isolated, non-editable virtual environment:

```bash
python tools/replay_javascript_history.py \
  --source /absolute/checkwash \
  --python /absolute/candidate-venv/bin/python \
  --manifest /absolute/checkwash/benchmarks/javascript-history/v0.4.2/manifest.json \
  --output /absolute/receipts/javascript-history
```

The runner requires committed manifest bytes and a clean source checkout. It
verifies the candidate's installed package against that source, clones the
CheckWash source locally to the exact v0.4.1 commit
`ea726c9cbd172b838bcf42b2c9969759e4ca358e`, and installs that baseline into a
second isolated environment. Network access is needed for hash-verified public
sources and Python build dependencies. It never executes downloaded JS/TS,
repository hooks, an upstream package manager, or an upstream test runner.

For every file, the runner makes two isolated synthetic Git commits containing
the unchanged full bytes at the original path. Both installed CLIs run the same
range with findings JSON, coverage JSON and a separate IR report. The output
retains source bytes, source/projection provenance, raw stdout/stderr, commands,
exit codes and report hashes. Assertion counts and coverage gaps expose cases
where a pass includes unsupported syntax. A candidate block on any preserving
row fails the receipt; baseline blocks remain visible comparisons. Engine or
report-integrity errors also fail. Nonblocking findings remain fully visible.
The baseline checkout, virtual environment and synthetic Git repositories live
in a new `checkwash-js-history-*` directory in the operating system's temporary
directory. Archive the requested output directory; it holds complete source
bytes and evidence without copying disposable environments or Git databases.

The final `receipt.json` uses schema version 1. Its `status` is `passed` or
`failed`; `source_sha`, `manifest_sha256`, and `baseline_source_sha` bind the run.
`summary` separates preserving rows, descriptive controls, baseline/candidate
preserving blocks and failed observations. `cases` retains audit labels and
both observed outputs. Never relabel a case after seeing candidate output to
make this receipt pass; record any disagreement and review it separately.

The existing `checkwash sweep` traverses a consecutive commit range and is not
used here because this population was preselected by exact file identity. The
CLI and isolated-Git pattern follow `tools/qualify_assertions.py`; this runner
keeps historical source provenance and outcomes separate from its synthetic
assertion contracts and from the frozen historical sweep records.
