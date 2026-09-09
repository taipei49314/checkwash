# Natural quality acceptance

The original [protocol](protocol.json) remains the acceptance contract. The
[preparation preregistration](natural-preparation-v1.json) freezes the next
100 single-parent path-history commits per original repository and the engine
at `8800af906fd332ee24e700aa16785c4f7edfdf6b`. This batch is source preparation;
it does not run Checkwash or change a detector.

The `quality natural review preparation` workflow authenticates the original
90-candidate artifact, verifies that its IDs and parent IDs still form the
history prefix, and preserves original configuration bytes. It appends the
next 100 candidates per repository in API source order. Exhaustion, page limits
and acquisition errors remain in the receipt. No content or prediction filter
selects candidates.

The artifact contains:

- `original-manifest.json`, the original protocol and the preregistration.
- `history/`, ordered API commit/parent pages, omissions and shortfalls.
- `objects/`, deduplicated public configuration and context bytes, addressed by
  SHA-256. Git blob IDs and bounded-source failures are in each snapshot.
- `prepared-manifest.json` and its digest, with before/after tool-table keys,
  exact values, source references, and dependency/lock/pre-commit version
  mentions. These are independent static review aids, never human labels or
  verified activation. A version range is not an exact version.
- `review.md`, per-repository review pages, `review.csv` and
  `review-labels.json`. Every human label starts `UNREVIEWED`.
- `summary.json` and the collection receipt. Collection time is not an engine
  performance measurement.

Only public Git objects are read. Subject working trees, programs, workflows,
plugins and dependencies are not executed or installed. Static context
discovery includes configuration basenames, root lockfiles, requirements and
GitHub workflow text. It cannot establish dynamic includes, actual invocation
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
