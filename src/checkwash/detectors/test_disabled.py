"""TEST_DISABLED: skip/xfail marker added, or a whole test unit disappeared."""

from __future__ import annotations

from checkwash.compat import removed_skip_guard
from checkwash.findings import (
    SHAPE_COLLECTION_CONTROL,
    SHAPE_GUARD_WEAKENED,
    SHAPE_INERT_MARK,
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
    SKIP_MARK,
    SUITE_KINDS,
    is_collection_control,
    marker_kind,
)
from checkwash.frontends.python.hook_guards import HOOK_MARKERS
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.markers import is_guarded_mark, is_setup_skip, skip_condition
from checkwash.ir.model import IR, judged_as_test

# What an added marker of each kind did. Any other kind, or none, is a plain
# disabling marker.
_WHAT = {
    FIXTURE_SETUP: "conftest fixture setup now ends every requesting test in skip/xfail",
    RUNTIME: "suite-level execution/report suppression added",
    COLLECTION: "suite-level collection control added",
    SETUP: "skip/xfail added to the setup this test runs",
}
# A skip mark on a conftest's `<suite>` unit comes from its `pytestmark`,
# which pytest never reads there (#209 Q3).
_INERT = "pytestmark added to conftest.py, which pytest does not collect as a test module: it disables nothing"
# Its guard guards nothing either, so a guard made always true or removed
# there is reported in the same shape (#260).
_INERT_GUARD = "pytest does not collect conftest.py as a test module, so this pytestmark disables nothing"
# A runner decides whether focus stops anything: node:test honours it only
# under a flag set outside the file (#196 187.1).
_UNFOCUSED = (
    "focus elsewhere in this file; a runner that honours it stops this unit "
    "(node:test only under --test-isolation=none or --test-only)"
)


def finding_marker(finding: Finding, unit) -> str | None:
    """The disabling marker a TEST_DISABLED finding reports, or None for one that reports none.

    A marker-added finding is keyed by its marker's name (`detect`). The
    others report no marker of their own: a unit gone, rows removed, a guard
    weakened or removed. D6 judges the marker a finding reports, not the unit
    it sits on (#208), so this is the one place that reads the name back.
    """
    if finding.rule != "TEST_DISABLED" or finding.shape not in (SHAPE_MARKER_ADDED, SHAPE_COLLECTION_CONTROL):
        return None
    if unit is None or unit.delta is None:
        return None
    for name in unit.delta.markers_added:
        if make_fingerprint("TEST_DISABLED", finding.path, unit.qualname, name) == finding.fingerprint:
            return name
    return None


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
                    if file.role == "conftest" and kind == SKIP_MARK:
                        what, shape = _INERT, SHAPE_INERT_MARK
                    else:
                        what = _UNFOCUSED if name == "test.unfocused" else _WHAT.get(kind, "disabling marker added")
                        shape = SHAPE_COLLECTION_CONTROL if kind in SUITE_KINDS else SHAPE_MARKER_ADDED
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
                            shape=shape,
                        )
                    )
            for name in unit.delta.guards_weakened:
                # A skip in the setup this test runs says so, and names its
                # provider: its evidence is the fixture's or callback's line.
                # A collection hook names itself too: its guard is the
                # condition its effects fire under (#209 Q1). So does a mark:
                # only a `pytestmark` binding gives one a guard (#260 Q2). A
                # `collect_ignore` whose guard was removed names itself as a
                # hook does (#261 Q1); one whose guard now always fires keeps
                # the wording it has always had.
                was = removed_skip_guard(name, unit, file.constants_before)
                if is_setup_skip(name):
                    where, which = " in the setup this test runs", f" ({name})"
                elif name in HOOK_MARKERS or (was is not None and is_collection_control(name)):
                    where, which = " of the suite-level control", f" ({name})"
                elif is_guarded_mark(name):
                    where, which = "", f" (pytestmark: {name})"
                else:
                    where, which = "", ""
                if was is not None:
                    m = next(
                        (
                            x
                            for x in unit.after.markers
                            if x.name == name and skip_condition(x, unit.after) is None
                        ),
                        None,
                    )
                    message = f"{unit.qualname}: skip guard removed{where} (was {was!r}){which}"
                else:
                    m = next((x for x in unit.after.markers if x.name == name), None)
                    message = (
                        f"{unit.qualname}: skip guard{where} now always fires "
                        f"({(m.guard if m else name)!r}){which}"
                    )
                # A conftest's `pytestmark` disables nothing whatever its
                # guard says, so this is reported as the mark is (#209 Q3).
                inert = file.role == "conftest" and marker_kind(name) == SKIP_MARK
                if inert:
                    message = f"{message}: {_INERT_GUARD}"
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=message,
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=m.text, span=m.span) if m else None,
                        fingerprint=make_fingerprint(
                            "TEST_DISABLED", file.path, unit.qualname, f"guard:{name}"
                        ),
                        shape=SHAPE_INERT_MARK if inert else SHAPE_GUARD_WEAKENED,
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
