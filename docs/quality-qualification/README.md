# Quality preview qualification record

This is the historical preview candidate's engineering record, not v0.4
acceptance or release approval. The later [v0.3.4 publication](../releases/v0.3.4-public-launch.md)
retains these original results and acceptance conditions; its source-qualified
checks and frozen comparison failure are recorded separately.
Existing test labels, oracle gating and the pinned-tag release gate are retained.

## Fixed native comparison

- Candidate source: `8f8b5c6` (resolve the full source from the run).
- Hosted run: [34319864242](https://github.com/taipei49314/checkwash/actions/runs/34319864242).
- Python: 3.12 on hosted Ubuntu; exact installed dependencies and archive hashes
  are retained in that run's `quality-qualification/install.json` artifact.
- Tool versions: coverage 7.16.0, Ruff 0.16.6, mypy 2.3.1.
- Result: 45 native comparisons passed. The immutable packaged result is
  `src/checkwash/quality/qualification_data/results.json`; each profile records
  SHA256 hashes of that result and the copied qualification fixture.
- [Readable result](2026-09-09-native.json). No repository under review was
  executed; native tools ran on locally constructed trusted microfixtures in CI.
- Rule namespace and incompatible-pair definitions come from the
  [Ruff 0.16.6 registry](https://github.com/astral-sh/ruff/blob/0.16.6/crates/ruff_linter/src/registry.rs).
  Their effects are checked against native full selection sets, not only this table.

Earlier failing qualification receipts are retained in Actions: uncoded preview
catalog entries, family namespace expansion and custom TOML source extraction
were found and corrected. The failure results were not converted to passes.

## Historical candidate gates

`quality qualification` regenerates fixed-version profiles, validates actual
schema-1 reports, runs quality cases and verifies wheel/zipapp CLI process exits.
The normal nine-platform/Python combinations continue to run the full old suite
and the new tests. Normal CI also dogfoods the existing checkwash action.

The existing `test_pinned_tag_ships_the_current_source` fails while this candidate
differs from the advertised v0.3.3 tag. That is an actual outstanding release gate,
not an unexpected oracle drift. No test skip, expectation rewrite or tag is used
to hide the failure. Merge and release are separately governed.

## Acceptance still required

- Human review of the new fixture labels, as required by AGENTS.md.
- At least 90 frozen natural changes from six public repositories, including
  20 relevant changes per tool, with the sampling protocol frozen before analysis.
- Independent held-out labels and precision/recall/completeness measurements.
  No quality detection-rate or false-positive-rate claim is made from synthetic
  cases, prior test-tampering corpus scores, or the native comparison count.
- The 70% natural parsing-completeness threshold is unmeasured. All three adapters
  remain limited previews until that evidence exists. Enforce is an explicit
  base-policy capability; it is not a declaration of mature general coverage.
- Fixed-corpus timing and peak-memory receipts, final old-oracle byte comparison,
  and explicit release authorization before bump/tag/Release/downstream pins.

The complete approved contract remains in `docs/design/quality-v0.4.md`. This
record narrows public claims to completed evidence; it does not reduce that
contract's acceptance thresholds.
