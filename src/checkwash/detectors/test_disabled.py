"""TEST_DISABLED: skip/xfail marker added, or a whole test unit disappeared."""

from __future__ import annotations

from checkwash.findings import (
    SHAPE_COLLECTION_CONTROL,
    SHAPE_GUARD_WEAKENED,
    SHAPE_MARKER_ADDED,
    SHAPE_PARAM_CASES_REMOVED,
    SHAPE_UNIT_REMOVED,
    Evidence,
    Finding,
    make_fingerprint,
)
from checkwash.frontends.python.conftest_controls import (
    COLLECTION,
    FIXTURE_SETUP,
    RUNTIME,
    SETUP,
    SUITE_KINDS,
    marker_kind,
)
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.model import IR, judged_as_test

# What an added marker of each kind did. Any other kind, or none, is a plain
# disabling marker.
_WHAT = {
    FIXTURE_SETUP: "conftest fixture setup now ends every requesting test in skip/xfail",
    RUNTIME: "suite-level execution/report suppression added",
    COLLECTION: "suite-level collection control added",
    SETUP: "skip/xfail added to the setup this test runs",
}
# A runner decides whether focus stops anything: node:test honours it only
# under a flag set outside the file (#196 187.1).
_UNFOCUSED = (
    "focus elsewhere in this file; a runner that honours it stops this unit "
    "(node:test only under --test-isolation=none or --test-only)"
)


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
            continue
        for unit in file.units:
            if unit.before is not None and unit.after is None:
                # whole unit disappeared
                text = "\n".join(a.text for a in unit.before.assertions) or unit.qualname
                identity = "\n".join(fingerprint_text(file.path, a) for a in unit.before.assertions) or unit.qualname
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=f"{unit.qualname}: test unit disappeared",
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=text, span=unit.before.span),
                        after=None,
                        fingerprint=make_fingerprint("TEST_DISABLED", file.path, unit.qualname, identity),
                        shape=SHAPE_UNIT_REMOVED,
                    )
                )
                continue
            if unit.delta is None or unit.after is None:
                continue
            if unit.delta.markers_added:
                marker_by_name = {m.name: m for m in unit.after.markers}
                for name in unit.delta.markers_added:
                    m = marker_by_name.get(name)
                    kind = marker_kind(name)
                    what = _UNFOCUSED if name == "test.unfocused" else _WHAT.get(kind, "disabling marker added")
                    findings.append(
                        Finding(
                            rule="TEST_DISABLED",
                            severity="warn",
                            message=f"{unit.qualname}: {what} ({name})",
                            path=file.path,
                            unit=unit.qualname,
                            before=None,
                            after=Evidence(text=m.text, span=m.span) if m else None,
                            fingerprint=make_fingerprint("TEST_DISABLED", file.path, unit.qualname, name),
                            shape=(
                                SHAPE_COLLECTION_CONTROL
                                if kind in SUITE_KINDS
                                else SHAPE_MARKER_ADDED
                            ),
                        )
                    )
            for name in unit.delta.guards_weakened:
                m = next((x for x in unit.after.markers if x.name == name), None)
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: skip guard now always fires "
                            f"({(m.guard if m else name)!r})"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=m.text, span=m.span) if m else None,
                        fingerprint=make_fingerprint(
                            "TEST_DISABLED", file.path, unit.qualname, f"guard:{name}"
                        ),
                        shape=SHAPE_GUARD_WEAKENED,
                    )
                )
            if unit.delta.param_cases_removed:
                n = unit.delta.param_cases_removed
                disabled = unit.delta.param_cases_disabled
                before_n = unit.before.param_cases if unit.before else None
                after_n = unit.after.param_cases
                live_after = after_n if after_n is not None else 1
                if disabled:
                    # A marked row is still written down, so the live count
                    # can stay put (F-063: one row marked, one appended).
                    # Say what happened rather than "deleted (2 -> 2)".
                    message = (
                        f"{unit.qualname}: {n} of {before_n} parametrized case(s) no longer "
                        f"run ({disabled} disabled, {n - disabled} deleted; live count "
                        f"{before_n} -> {live_after})"
                    )
                else:
                    message = (
                        f"{unit.qualname}: {n} parametrized case(s) deleted "
                        f"({before_n} -> {live_after})"
                    )
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=message,
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=f"parametrize cases: {after_n}", span=unit.after.span),
                        fingerprint=make_fingerprint(
                            "TEST_DISABLED", file.path, unit.qualname, "parametrize"
                        ),
                        shape=SHAPE_PARAM_CASES_REMOVED,
                    )
                )
        # Focus that turns nothing off in its own file can still turn off the
        # rest of the suite, which is what Mocha and Jasmine do (#196 187.4).
        # A unit the focus already stops carries the report instead.
        focus = file.suite_focus_added
        if focus is not None and not any(
            unit.delta is not None and "test.unfocused" in unit.delta.markers_added
            for unit in file.units
        ):
            findings.append(
                Finding(
                    rule="TEST_DISABLED",
                    severity="warn",
                    message=(
                        f"focus added ({focus.text}); under a runner that applies focus "
                        "suite-wide, every test outside this file stops"
                    ),
                    path=file.path,
                    unit=None,
                    before=None,
                    after=Evidence(text=focus.text, span=focus.span),
                    fingerprint=make_fingerprint("TEST_DISABLED", file.path, "<file>", focus.name),
                    shape=SHAPE_MARKER_ADDED,
                )
            )
    return findings
