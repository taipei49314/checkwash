"""TEST_PATCHES_SUBJECT: a stand-in newly reaches an existing test oracle.

The v0.1.25 gap was first described as the test-local counterpart of
``CONFTEST_PATCHES_PROD``: production and the assertion could remain
byte-identical while a new assignment made the oracle exercise a stand-in.
That history still explains the rule, but the current family uses one shared
effect/reach model for test-local installs and applicable conftest installs.

The discriminator is an **effect x oracle semantic multiset**, not whether a
patch spelling was newly added.  For each aligned unit, ``O[q]`` counts each
occurrence of a complete canonical oracle shape and ``R[e,q]`` counts the
occurrences reached by semantic effect ``e``.  The event lower bound is::

    max(0, R_head[e,q] - R_base[e,q] - max(0, O_head[q] - O_base[q]))

New identical oracle occurrences are spent first.  Moving an existing
assignment before another existing oracle, or expanding a patch context into
a persistent installation, is therefore visible; merely adding an identical
already-reached oracle is not.  A finding still requires positive repository
ownership and exact canonical subject reach.  Replacing
``billing.RETRY_DELAY`` under an assertion about charging remains routine;
replacing ``billing.invoice_total`` under an oracle for that call does not.

The bounded model tracks lexical patch/MonkeyPatch contexts, helper-scoped
decorators, and definite straight-line restore endpoints.  Fixture and hook
decorators are resolved through aliases at definition time, including literal
``name=`` / ``specname=``.  ``mocker.patch`` and MonkeyPatch methods require a
proven live fixture receiver (or a proven ``pytest.MonkeyPatch`` construction),
not a coincidental local name.  Conftest applicability is resolved separately
on base and head through ancestor/nearest-provider fixture graphs, including
autouse, literal parameters/``usefixtures``, and transitive dependencies; an
unchanged dormant fixture can thus become newly applicable without gaining a
new install line.

Residuals are explicit.  xunit ``setUp`` / ``setup_method`` activation is not
modelled.  Dynamic ``request.getfixturevalue`` and plugin-only fixtures are
outside the repository graph, as are fixture providers inherited through a
test class's Python base-class MRO.  Computed or branch-dependent restores,
stored patcher ``start``/``stop``, cross-ordered undo between multiple
``MonkeyPatch`` objects that resurrects an effect in a disjoint interval, and
``ExitStack.enter_context`` have no definite lifetime.  Arbitrary
interprocedural return/receiver provenance is not inferred; dynamic, starred,
or transitively forwarded helper arguments require an exact binding.
Unchanged tests are discovered for a changed conftest only through
literal target-leaf/attribute needles.  After a ``sys.modules`` replacement,
dotted native ``import app.billing as billing`` and from-parent
``from app import billing`` are not definite positives; exact leaf imports and
literal ``importlib.import_module`` remain modelled.  A deeply nested conftest
is normally registered too late for ``pytest_sessionstart``, so only initial
conftests (the repository root or an immediate ``test*`` directory) are
treated as applicable.  Runtime-computed targets, ``respx``/``responses``,
and other HTTP-mock dialects also remain outside this bounded proof.

Like every oracle rule, severity still comes from repair evidence (SPEC §5
E1): swapping a collaborator out is routine when production moved with the
test.
"""

from __future__ import annotations

import ast

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.markers import parse_expr
from checkwash.ir.model import IR
from checkwash.pyenv import known_baseline
from checkwash.standins import (
    install_reaches,
    new_unit_standin_installs,
    target_is_repo_owned,
)


def _legacy_names_in(expr: str | None) -> set[str]:
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _legacy_reached(side) -> set[str]:
    """Frozen IR-v1 reachability for producers without internal metadata."""
    names: set[str] = set()
    for assertion in side.assertions:
        names.update(assertion.left_names)
        names.update(assertion.right_depends_on)
        names |= _legacy_names_in(assertion.left)
    hop: set[str] = set()
    for name in names:
        definition = side.bindings.get(name)
        if definition is not None and "\x1f" not in definition:
            hop |= _legacy_names_in(definition)
    return names | hop


def detect(ir: IR) -> list[Finding]:
    # Ownership is positive evidence assembled by the engine. In particular,
    # an undeclared external import is not promoted merely because no manifest
    # entry denied it, while a relative import remains local even when its leaf
    # shares a stdlib name.
    owned = set(ir.globals.first_party_roots)
    legacy_deny = known_baseline() | set(ir.globals.third_party_roots)
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            # Condition 1.
            if unit.before is None or unit.after is None:
                continue
            if (
                unit.before.standin_installs is None
                or unit.after.standin_installs is None
            ):
                # Exact compatibility path for externally constructed IR-v1:
                # target-only newness, deny-list ownership, and name-based
                # reach. Richer parsed sides never enter this branch.
                was = {target for target, _attr in unit.before.patches}
                reached = _legacy_reached(unit.after)
                for target, attr in unit.after.patches:
                    if (
                        target in was
                        or target.split(".")[0] in legacy_deny
                        or attr not in reached
                    ):
                        continue
                    findings.append(
                        Finding(
                            rule="TEST_PATCHES_SUBJECT",
                            severity="warn",
                            message=(
                                f"{unit.qualname}: this test now replaces {target}, which its own "
                                "assertions check — the oracle runs against the stand-in"
                            ),
                            path=file.path,
                            unit=unit.qualname,
                            after=Evidence(text=target, span=(0, 0)),
                            fingerprint=make_fingerprint(
                                "TEST_PATCHES_SUBJECT",
                                file.path,
                                unit.qualname,
                                target,
                            ),
                        )
                    )
                continue
            owned_candidates = [
                install
                for install in new_unit_standin_installs(
                    unit.before, unit.after
                )
                if target_is_repo_owned(install.target, owned)
            ]
            by_effect = {}
            for install in sorted(
                owned_candidates,
                key=lambda candidate: (
                    candidate.effect_identity,
                    candidate.target,
                    candidate.finding_target,
                    candidate.text,
                ),
            ):
                by_effect.setdefault(install.effect_identity, install)
            candidates = list(by_effect.values())
            if not candidates:
                continue
            for install in candidates:
                if not install_reaches(
                    install,
                    unit.after,
                    (
                        unit.after.standin_imports
                        if unit.after.standin_imports is not None
                        else file.standin_imports or {}
                    ),
                ):  # condition 3
                    continue
                target = install.finding_target
                findings.append(
                    Finding(
                        rule="TEST_PATCHES_SUBJECT",
                        severity="warn",  # gating escalates without a prod change
                        message=(
                            f"{unit.qualname}: this test now replaces {target}, which its own "
                            f"assertions check — the oracle runs against the stand-in"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        after=Evidence(text=target, span=(0, 0)),
                        fingerprint=make_fingerprint(
                            "TEST_PATCHES_SUBJECT", file.path, unit.qualname, target
                        ),
                    )
                )
    return findings
