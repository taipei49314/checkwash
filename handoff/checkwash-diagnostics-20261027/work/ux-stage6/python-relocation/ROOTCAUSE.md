# Two Python relocation positives: read-only source diagnosis

State: DRAFT_NOT_ADOPTED / NO_PRODUCT_OR_PYTEST_CALLS_BY_THIS_AGENT.
Product/source remains `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`.
The source, old expectations, gates, protected contracts, all stage5 outputs,
qualifications and remote backup are untouched. The permanent human-authorized
PJU policy remains in force; no pool investigation or host change occurred.

## What is actually observed

The existing stage5 full native JUnit reports both named tests failing their
unchanged `assert verdict == 'pass'`: actual value is `'block'`.
It does not print the full findings or optional oracle proof fields for these
tests. Claims below about the first rejecting branch are source reasoning,
not a newly measured API/CLI result. Root owns any new unchanged-fbc API arms.

| Existing test | Original claim | Native full result | Source diagnosis |
|---|---|---|---|
| issue263 / tests moved under a class string mark | move live tests into TestAdd; obsolete Python<2.6 mark does not disable them | BLOCK vs expected PASS | missing strict root is the first independent blocker; new nonliteral mark binding then rejects environment; class/receiver/scope are further mismatches |
| issue358 / test moved under own-mark gate | unmarked test moves with identical function-scoped autouse fixture whose first guard is false | BLOCK vs expected PASS | all-module Name(request) guard rejects before unit/context construction; decorated helper would reject next |

## #263: consumer gap plus a bounded product gap

`tests/test_issue263_string_conditions.py:42-48` calls analyze without a
root_reader or head_reader. `_relocation_startup` (`engine.py:1713-1752`)
requires strict root knowledge for ancestor initializers. A missing reader
means unknown, not known absence. Restoring credit without that knowledge
would undo the startup/import protection added in D179. The test helper needs
a **closed-fixture API migration**, preserving every expected verdict.

Supplying a closed root is necessary but, by source inspection, insufficient:

1. `old_python = pytest.mark.skipif(...)` is a Call-valued assignment.
   `oracle_credit.py:139-144` admits literal assignments only, hence rejects
   the after environment before examining the class.
2. The class left after removing selected methods still differs from the
   former top-level environment (`:114-121`). A pytestmark alias remains.
3. `class_name` (`:180`) and the `self` parameter in args/declaration (`:187-205`)
   remain in whole-unit and assertion proofs. Simply ignoring one does not
   discharge the others.

The specific string is a pure version comparison. The existing D6 environment
matrix is Python3.11/3.12/3.13/3.14 × Windows/Linux/macOS
(`compat.py:29-41`); `< (2,6)` is false throughout that declared matrix.
This is stronger than merely "live somewhere". A newly introduced gate which
skips Windows must not be erased as equivalent merely because D6 considers it
a compatibility gate.

A narrow future product proof can recognize a **passive collection wrapper**:
plain Test* class, no bases/keywords/decorators/constructor/setup/helper/class
state; body contains only selected plain test methods, documentation/pass and
an inactive, known pytestmark. The leading self argument must have no annotation,
default or use in the body. Unique marker bindings may be removed only when
their sole loads are the admitted pytestmark declaration and their pytest/sys
authority is unambiguous. No other class/module context is erased.

This is not a reason to weaken the old expectation or to exempt every class.
If any obligation is unknown, the original conservative BLOCK remains.

## #358: absence of a skip is not by itself fixture equivalence

This test already passes a strict closed HEAD map: APP plus both modified/added
test modules. Both source modules contain the same GATE definition. The selected
plain test has no mark. The marker-aware frontend drops the setup skip for that
unit (`frontend.py:4639-4680`, `own_marks.resolve`). Nevertheless the separate
D179 proof kernel scans **every** Name in the module, not just the selected unit
(`oracle_credit.py:93-101`). The fixture parameter/body spell request, so the
kernel returns immediately. If that check were bypassed alone, decorated helper
admission at `:133-137` would still return None.

The safe candidate is not "all unchanged fixtures are equal". request.node.name,
nodeid/path/keywords/class identity, a preceding mutation, teardown, wider scope
or another autouse dependency may change oracle semantics on relocation. The
specific fixture has a sole `if` statement. Its first `and` operand is the known
framework presence read get_closest_marker('slow'). When OwnMarks is known and
slow is absent, Python short circuit prevents both the os.environ lookup and
the skip body from executing. A narrow per-unit proof can admit only that
no-effect fixture declaration, retaining the declaration's full exact AST in
the environment hash; it need not erase, execute or follow arbitrary helpers.

The engine's startup-known predicate must still reject unreadable/star/mark-
adding conftests, plugin configuration which can load marks, initializer changes
and missing root context. Reusing OwnMarks must not lose that engine/chain
provenance. No fixture parameters/other fixtures, assignments, prefix/suffix,
yield/finalizer/else body, request reassignment or unknown decorator qualify.

## Proposed movement and remaining scope

No golden relabel is proposed. These are candidate proof domains only: no
future PASS is predicted. In particular, #263 supplies no closed implementation
of app.calc.add; even an unused self in the selected body does not prove that
its callee ignores caller locals/receiver/qualname. Explicit bounded call-effect
and identity closure is an unresolved prerequisite, otherwise keep UNKNOWN.
Supplying only the test module in a closed-root map does not close that gap.
#263 also requires its caller to state a closed snapshot. The product proposal
is **not ready to apply**: the exact normalization helpers and counterexamples
must be implemented/reviewed and run against a new source identity first.
`MINIMAL-PATCH-PROPOSAL.md` gives the exact admission boundary and insertion
points; `NEGATIVE-CONTROLS.md` defines the necessary future controls. These are
not executed movements or acceptance receipts. No prediction is used to erase
the original full-suite failures or old source evidence.

Out of scope: blanket context compensation, getters/call-graph equivalence,
class-base resolution, runtime plugin execution, existing .gwcase label changes,
strength/severity/alignment changes, or releasing the candidate.
