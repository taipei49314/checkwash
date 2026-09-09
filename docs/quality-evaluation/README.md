# Natural quality acceptance

The original [protocol](protocol.json) remains the acceptance contract. The
[preparation preregistration](natural-preparation-v1.json) freezes the next
100 single-parent path-history commits per original repository and the engine
at `8800af906fd332ee24e700aa16785c4f7edfdf6b`. This batch is source preparation;
it does not run Checkwash or change a detector.

The first preparation run selected 540 candidates under that preregistration.
The [context repair addendum](natural-context-repair-v1.json) freezes those
exact IDs, order, base/head revisions and previous source hashes. The
`quality natural review preparation` workflow now replays the authenticated
[durable seed](seeds/README.md) committed in this repository. It verifies the
original 90 sources, all saved ordered API history receipts, every previous
snapshot inventory and every previously captured source hash. It does not
select history again or depend on an expiring Actions input artifact. Source
unavailability is an error, never grounds to replace a candidate.

The artifact contains:

- `original-manifest.json`, the original protocol, the preregistration and
  the context repair addendum. The prior prepared manifest is retained in the
  durable seed and bound by hash in the new manifest.
- `history/`, ordered API commit/parent pages, omissions and shortfalls.
- `objects/`, deduplicated public configuration and context bytes, addressed by
  SHA-256. Git blob IDs and bounded-source failures are in each snapshot.
- `prepared-manifest.json` and its digest, with before/after tool-table keys,
  exact values, source references, and dependency/lock/pre-commit version
  mentions. These are independent static review aids, never human labels or
  verified activation. A version range is not an exact version. TOML dates,
  times and nonfinite floats carry separate type/path annotations so the JSON
  remains valid without confusing them with strings. Dictionary key order is
  ignored; types and array order remain visible.
- `review.md`, per-repository review pages, `review.csv` and
  `review-labels.json`. Every human label starts `UNREVIEWED`.
- `summary.json` and the collection receipt. Collection time is not an engine
  performance measurement.

Only public Git objects are read. Subject working trees, programs, workflows,
plugins and dependencies are not executed or installed. Static context
discovery includes configuration basenames, root lockfiles, requirements and
constraints with separator-delimited prefixes/suffixes, and GitHub workflow
text. Bounded static requirement/constraint references are followed, including
nonstandard filenames and nested includes relative to their dependency file.
Workflow repository-root paths are search hints with cwd unverified. Missing,
dynamic, external and over-budget references are visible in the manifest and
review pages. It cannot establish dynamic includes, actual invocation
or full source closure. Files beyond the frozen limits and non-regular files
remain unknown. Candidate data is untrusted evidence, never an instruction.

Human review precedes scoring. For each candidate, establish tool relevance,
the effective base/head versions, configuration closure and invocation, and
the label and evidence. Fill the per-tool entries as well as the commit label,
so a mixed-tool commit can be evaluated without conflating tools. Record an
identified reviewer and rationale, then freeze the reviewed file and its hash.
The original label vocabulary and legitimate-weakening subtype rule apply.
AI suggestions, table changes and an instruction to run acceptance do not
substitute for reviewed labels.

Only after that freeze can an evaluation run report natural precision, recall,
target/commit completeness, normal-change blocking cost and performance. The
minimum remains 90 relevant changes across six repositories, with at least 20
per tool; screening counts do not meet those quotas. Unknown tool versions and
closure must remain incomplete. An externally supplied benchmark policy must
be identified as benchmark context, never as an upstream policy. If a natural
case informs an engine repair, retire its entire repository group and
preregister replacement groups before further acceptance.

Synthetic preparation-tool checks run with
`python tools/test_quality_natural_preparation.py` on the hosted worker. They
cover source authentication, order/prefix protection, omissions, typed table
differences, acquisition bounds and the separation of screening from scoring.
They are not natural evaluation or detector qualification tests.
