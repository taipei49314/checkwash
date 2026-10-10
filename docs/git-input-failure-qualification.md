# Git input failure qualification

This round addresses one input contract defect: failed Git reads previously
looked like missing source or a search with no hits. Range blobs now use an
immutable tree inventory and bounded OID batches. Process status, type, size,
delimiter, ordered identity and content hash are checked. A missing required
side is an error; opaque gitlink entries retain their existing non-file
meaning. Existing detector rules, severity, gate thresholds and expected
fixtures are unchanged.

Single-path reads verify content identity and check the tree before accepting
a missing response. Whole-tree grep only treats clean exit 1 as no match.
Startup failures, timeout, incomplete records and nonzero status retain an
error. Range references are resolved before diff/context/config reads; the
three-dot merge-base also receives those frozen endpoints. Worktree before,
labels, config, allowlist and manifests use one frozen HEAD; a HEAD movement
around status collection is an error. This does not make filesystem reads
atomic or claim to detect a ref that changes and changes back between checks.
Worktree reads distinguish absence from permission failure and disappearance
after stat, and reuse the bounded snapshot search. Status records are checked
before reading source; malformed, duplicate or unrepresentable paths fail.
This includes refusing an ambiguous staged-delete/untracked-recreation pair
for the same path rather than silently choosing one record.
Sweep reads the original commit object and verifies its identity before
classifying a root. A shallow boundary still has a parent in that object;
an unavailable parent therefore counts as an error, not a skipped root.

The qualification workflow uses only generated repositories. The 111 new cases
include actual loose object removal/corruption after inventory, batch protocol
faults, valid-looking output with nonzero status, startup/timeout, grep status
and protocol faults, CLI failure without an ordinary verdict, permission
failure, and readable empty/missing/rename behavior. They include normal
controls as well as faults, and must not all be described as fault trials.
The follow-up adds root-search empty/NUL/status checks, both inventory entry
points, worktree protocol checks and actual shallow-history qualification.
CLI integration covers malformed reverse caller discovery and actual ref
movement during three-dot and worktree processing, including fixed base-side
policy after the branch moves and an error if HEAD moves during status.
Empty successful grep output, empty NUL records and success with stderr are
errors. Only clean status 1 means no match; a truly empty tree remains valid.
Existing CLI, opaque
submodule, snapshot and performance tests run unchanged. Source editing and
receipt collection on the work machine do not execute these tests.

Validation is pending when this patch is first published. Read the exact-head
remote receipts before making a success claim. This is a new source candidate,
not approval or replacement of b6e6f3a or the 8c70efb reference. No historical
cost, first measurement, freeze, release or tag is performed here. The source
limits in GitSnapshot are retained: selected regular source files 1 MiB,
selected total 64 MB, inventory 200,000 paths, batch 256 OIDs. Commit objects
used to establish parents have a 1 MB limit. New complete
inventory and search response bounds reject oversize data, never truncate.
Refusals must be accounted for in any future measurement with the original
denominator. Old reference input-failure behavior remains a separate
measurement qualification limitation; it is not silently patched.
