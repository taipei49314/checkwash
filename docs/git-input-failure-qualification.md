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
error. Range references are resolved before diff/context/config reads.
Worktree reads distinguish absence from permission failure and disappearance
after stat, and reuse the bounded snapshot search. Sweep counts a commit as a
root only from its parent record; an input failure counts as an error.

The qualification workflow uses only generated repositories. The 44 new tests
include actual loose object removal/corruption after inventory, batch protocol
faults, valid-looking output with nonzero status, startup/timeout, grep status
and protocol faults, CLI failure without an ordinary verdict, permission
failure, and readable empty/missing/rename behavior. Existing CLI, opaque
submodule, snapshot and performance tests run unchanged. Source editing and
receipt collection on the work machine do not execute these tests.

Validation is pending when this patch is first published. Read the exact-head
remote receipts before making a success claim. This is a new source candidate,
not approval or replacement of b6e6f3a or the 8c70efb reference. No historical
cost, first measurement, freeze, release or tag is performed here. The source
limits in GitSnapshot are retained: selected regular source files 1 MiB,
selected total 64 MB, inventory 200,000 paths, batch 256 OIDs. New complete
inventory and search response bounds reject oversize data, never truncate.
Refusals must be accounted for in any future measurement with the original
denominator. Old reference input-failure behavior remains a separate
measurement qualification limitation; it is not silently patched.
