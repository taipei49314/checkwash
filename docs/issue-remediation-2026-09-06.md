# September 6 issue remediation candidate

This source candidate addresses issues [#126–#132](https://github.com/taipei49314/checkwash/issues/132).
It is unreleased. Installing v0.2.13 still installs the published behavior;
the package version and recommended Action pin have not advanced.

## Exemptions and stored expectations

#126 was already fixed by merged PR #125. A fresh 32-test real-git replay
against exact main `8f3fecf8e6b0690ed38ab473091bc14676b8e10a` confirmed the
content-bound identities and retirement of the old file-wide keys. The issue
is closed as fixed in source, with public-artifact availability still pending.

#129 adds the stored-file form of EXPECTED_VALUE_CHANGED. A modified recognized
snapshot/golden/expected file, without a parsed production-symbol change or
opaque production change, reaches the existing oracle gate. A production-only
comment does not grant repair credit. The default snapshot paths also include
`**/expected/**` and `**/*.expected`.

This new form has a file-scoped v2 fingerprint binding both contents. Exact
approval can match again; a different before or after cannot reuse it. Existing
assertion-level EXPECTED_VALUE_CHANGED keys retain their scheme. SARIF labels
the stored form `checkwash/v2` and malformed v2 keys are rejected.

The role is a naming convention, not proof that a specific test reads a file.
New/deleted expectations and unclassified data are outside this added event.
The old co-change policy is preserved: an unrelated new production function
or opaque production change can still leave a golden rewrite at warning.

## Conftest stand-ins

#127 resolves first-party root/src targets using strict repository snapshots,
so an unchanged production module need not appear in the diff. #128 recognizes
imported unittest.mock patch and patch.object forms, including aliases,
decorators, context managers and supported start calls. Constructing an unused
patch object is not treated as activating it.

The implementation checks local bindings and distinguishes standard pytest
fixture parameters from unrelated objects. It preserves external stubbing
controls. Custom import roots, dynamic factories/wrappers and fixture overrides
from ancestors or plugins remain outside the bounded target analysis.

Callers of analyze/build_ir that encounter these targets must supply the
existing strict root_reader callback. Unknown source, a failed required read
or an exhausted target-probe budget is an engine error, not a proven external
dependency. CLI, sweep and the repository's supported case adapters supply
complete snapshots; custom callers must do so too.

## Python oracle coverage and bounded precision

#130 recognizes a complete sequence of concrete literal calls preserved by
parametrize, fixture(params=), or a literal loop. It keeps expected values on
both sides for ordinary detectors. Reused mutable row bindings, altered inputs,
dynamic rows and unknown execution context do not receive equivalence credit.
Unsupported forms retain the ordinary frontend and existing restructure
compensation, which can still warn/pass for some weakened tables.

#131 preserves result-wrapper evidence through one-hop bindings, recognizes
direct conditional AssertionError oracles, and handles a narrowly transparent
two-field equality class when its operands are proven built-in scalars. This
does not interpret arbitrary custom __bool__, __eq__ or Python control flow.

Bounded literal-table rewrites also retain evidence when a result is wrapped
in `abs`, or literal input is filtered through `isalnum` and lowercased.
The added SUBJECT_NORMALIZED records cannot waive an ordinary finding or
grant equivalence credit. Matching reserves unchanged raw rows first, so
adding wrapped coverage beside all original cases does not report a lost
oracle. Fingerprints bind concrete subjects, operator and expectation;
source locations remain report evidence and do not change identity.

Redundant normalization can suppress a finding only through a bounded,
non-executing projection of a closed literal call against unchanged production.
Test package initializers, conftests and sibling collected modules are checked
for executable effects before optional precision is granted. The proof concerns
the current concrete expression, not every possible future production mutant.
External plugins, custom import hooks and arbitrary runtime introspection are
not established by this source check.

Repository pytest configuration is checked too: custom collection names and
plugin activation cannot hide executable sibling modules from that check.
Unsupported options withhold optional precision. The complete inventory still
inspects all conventional collected siblings when a supported configuration
limits collection to literal descendant test paths.

The optional proof inventory is deliberately small: fewer than 64 nonempty
Python source paths, with additional source/AST/read bounds. Missing, incomplete
or over-budget discovery keeps ordinary findings. Working-tree analysis sees
local untracked Python files too, so a local environment or generated source
can withhold precision that a smaller committed tree permits. These are
different snapshots; no cross-mode equality claim is made for different input
trees. Ordinary importer searches retain their prior behavior.

## Qualification and maintainer review

New regression controls pair actual pytest failures/successes with engine
verdicts, including package/conftest/sibling rebinding, unused versus activated
patchers, mutable row aliasing and stand-alone stored expectations. Source
replays use immutable captured trees and identify their engine source.

The original research records and published-version measurements remain
historical. #132 tracks the remaining population; this work does not claim all
559 saved families are fixed. Source improvements in CASE_026_leap and
CASE_029_flatten require review of the frozen refactor records; the repaired
tamper case 026-normalize also needs its captured expectation reviewed. The legacy
frozen wrapper lacks the new strict callbacks, so its results alone do not
qualify the precision path; complete-snapshot replays are recorded separately.

SPEC/THREATMODEL and frozen-record updates are supplied as a separate exact
maintainer review patch. They have not been applied, and an independent human
review of the new fixture labels is not claimed. Release qualification and
later recommended Action adoption remain separate steps.
