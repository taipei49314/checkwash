"""TEST_PATCHES_SUBJECT: the test replaced the thing its own assertion checks.

`CONFTEST_PATCHES_PROD` reads conftest files only, so the same swap one scope
lower was silent — ranked #2 of the attacks left open after P0, ★★★★★ silence,
and prod and the assertion line both stay byte-identical:

    def test_invoice_total(monkeypatch):
        monkeypatch.setattr(billing, "invoice_total", lambda *a: 105.3)
        assert billing.invoice_total(items, 0.053) == 105.3   # the stand-in

**The problem here is not detection, it is discrimination.** In a conftest,
patching first-party code is exceptional: one autouse fixture swaps the module
under test for the whole suite. Inside a test function it is *the normal way to
write a unit test*, and the acceptance line for this work — "new first-party
patch target in a test unit" — taken literally, fires on every commit that adds
a mock. So three conditions, all required:

1. **The unit existed before.** A brand-new test that mocks is a test that was
   written with a mock; only an existing oracle can have a stand-in inserted
   under it.
2. **The patch is new**, base side against head side.
3. **The patched attribute is reached by this unit's own assertions.** This is
   the discriminator and it is the whole design. Replacing `billing.RETRY_DELAY`
   under an assertion about charging makes the test fast. Replacing
   `billing.invoice_total` under `assert billing.invoice_total(...) == 105.3`
   replaces the subject of the oracle.

Like every oracle rule it earns severity from repair evidence (SPEC §5 E1):
swapping a collaborator out is routine when production moved under the test.

Residuals, open by design and not quietly: a stub installed by a fixture the
unit merely requests; targets built at runtime; `respx`/`responses` and the
other HTTP-mock dialects; an attribute reached only through a helper; and an
attribute named on the *expectation* side of a non-literal comparison, where
the IR keeps names but not the expression.
"""

from __future__ import annotations

import ast

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.markers import parse_expr
from checkwash.ir.model import IR
from checkwash.pyenv import known_baseline


def _names_in(expr: str | None) -> set[str]:
    """Names and attribute labels in an expression.

    `left_names` collects `ast.Name` ids only, so `billing.invoice_total(x)`
    yields `billing` and not the attribute that actually names the code under
    test — which is the half a patch target is matched on.
    """
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _reached(side) -> set[str]:
    """Every name this unit's assertions touch, through one hop of bindings.

    The direct set alone was not enough, and the corpus is what said so: across
    128 real patch sites the reach test rejected every one — correctly — but it
    also showed that

        result = billing.invoice_total(items, 0.053)
        assert result == 105.3

    puts the patched attribute nowhere in the assertion. That is the *more*
    natural way to write this attack than naming the call inside the `assert`,
    so the first version of this rule missed the shape it exists for.

    One hop, the same bound `SUBJECT_NORMALIZED` draws, and a name bound more
    than once is refused rather than guessed at: `bindings` joins every
    right-hand side of such a name, and substituting that invented a false
    positive once already (flask `daf1510a4b`, D-042).
    """
    names: set[str] = set()
    for a in side.assertions:
        names.update(a.left_names)
        names.update(a.right_depends_on)
        names |= _names_in(a.left)
    hop: set[str] = set()
    for name in names:
        definition = side.bindings.get(name)
        if definition is not None and "\x1f" not in definition:
            hop |= _names_in(definition)
    return names | hop


def detect(ir: IR) -> list[Finding]:
    # Stdlib and the test ecosystem are denied here rather than through the
    # manifest set: faking time, sockets and the environment is hygiene, and
    # the list is a frozen vendored snapshot, so the judgement does not move
    # with the interpreter running the analysis (SPEC §8).
    deny = known_baseline() | set(ir.globals.third_party_roots)
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            # Condition 1.
            if unit.before is None or unit.after is None:
                continue
            was = {target for target, _attr in unit.before.patches}
            candidates = [
                (target, attr)
                for target, attr in unit.after.patches
                if target not in was  # condition 2
                and target.split(".")[0] not in deny
            ]
            # Only now: `_reached` parses every assertion subject in the unit,
            # and the overwhelming majority of units install no stand-in at all.
            if not candidates:
                continue
            reached = _reached(unit.after)
            for target, attr in candidates:
                if attr not in reached:  # condition 3
                    continue
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
    # File-level spelling of the same event: import resolution replaced the
    # subject provider before any test unit ran.  Keep the existing rule ID so
    # this follows the already-audited oracle policy; a new rule ID would need
    # a maintainer-only gating-table change.  Unit=None is intentional: the
    # newly added stand-in package must not cite its own symbols as repair
    # evidence for the replacement it caused.
    for path, module, before, after, test_path, trigger in ir.globals.runtime_subject_shadows:
        if before == after:
            message = (
                f"{test_path}: the already-winning provider {after} for imported "
                f"subject {module} changed after matching an alternate first-party "
                "provider — the oracle now runs against the changed stand-in"
            )
        else:
            message = (
                f"{test_path}: imported subject {module} now resolves to {after} "
                f"instead of {before} ({trigger}) — the oracle runs against a stand-in"
            )
        findings.append(
            Finding(
                rule="TEST_PATCHES_SUBJECT",
                severity="warn",
                message=message,
                path=path,
                unit=None,
                after=Evidence(text=f"{module} -> {after}", span=(0, 0)),
                fingerprint=make_fingerprint(
                    "TEST_PATCHES_SUBJECT", path, None, f"{module}:{before}->{after}"
                ),
            )
        )
    return findings
