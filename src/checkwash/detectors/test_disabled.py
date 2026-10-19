"""TEST_DISABLED: skip/xfail marker added, or a whole test unit disappeared.

Every finding's key is content-bound (#512, round 2 of #421):
`TEST_DISABLED/path/unit/v2:<64hex>`, built as the nine assertion-level rules'
keys are (`findings.assertion_identity`), over the legacy pre-image unchanged,
the finding's shape as the event kind, and what that shape changed (`_key`).
So one approved skip, guard change or parametrize row deletion covers no other
change to the same unit. Which markers pair, which move and how many findings
there are do not change: the marker identity alignment pairs on still leaves
the guard out (D-019, ruling 512.Q1 (a)).
"""

from __future__ import annotations

import json
from collections import Counter

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
    identity_text,
    make_assertion_fingerprint,
)
from checkwash.frontends.python.conftest_controls import (
    COLLECTION,
    FIXTURE_SETUP,
    HELPER,
    REBINDING,
    RUNTIME,
    SETUP,
    SKIP_MARK,
    SUITE_KINDS,
    is_collection_control,
    marker_kind,
)
from checkwash.frontends.python.hook_guards import HOOK_MARKERS
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.markers import is_guarded_mark, is_helper_skip, is_rebound, is_setup_skip, skip_condition
from checkwash.ir.model import IR, judged_as_test, param_tables

# What an added marker of each kind did. Any other kind, or none, is a plain
# disabling marker.
_WHAT = {
    FIXTURE_SETUP: "conftest fixture setup now ends every requesting test in skip/xfail",
    RUNTIME: "suite-level execution/report suppression added",
    COLLECTION: "suite-level collection control added",
    SETUP: "skip/xfail added to the setup this test runs",
    HELPER: "skip/xfail added to a helper this test calls",
    REBINDING: "a later binding of this test's name may replace it",
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


def _key(path: str, qualname: str, legacy_text: str, shape: str, *, before=None, after=None, context=None) -> str:
    """A finding's content-bound key (#512 Q2): `TEST_DISABLED/path/unit/v2:<64hex>`.

    `legacy_text` is what the legacy key hashed, so the identity holds that
    key's pre-image unchanged and every v2 key refines its legacy key. The
    event kind is the finding's shape. `before` and `after` are texts in
    `identity_text`'s form, and `context` is what the shape binds beyond
    them. No span, line, message, severity, file digest or revision label
    enters it, and there is no position: each shape binds its own texts.
    """
    return make_assertion_fingerprint(
        "TEST_DISABLED", path, qualname, legacy_text, before=before, after=after, kind=shape, context=context,
    )


def _marker_added_key(path: str, qualname: str, name: str, marker, shape: str) -> str:
    """A marker added: its complete text and the guard it was recorded with, null when none.

    Every shape a marker added reports takes it: a plain disabling marker,
    a suite-level control and a conftest's `pytestmark`. The guard is the
    marker's recorded one (`Marker.guard`): an imperative skip's enclosing
    `if`, and the condition a setup skip, a helper's skip or a later
    binding runs under. So a guarded skip and an unguarded one of the same
    name are two keys. Alignment still pairs markers without it (D-019).
    """
    text = marker.text if marker is not None else None
    guard = marker.guard if marker is not None else None
    return _key(path, qualname, name, shape, after=text, context={"guard": identity_text(guard)})


def _guards(name: str, unit, was: str | None, marker) -> tuple[str | None, str | None]:
    """(guard before, guard after) of a guard made always true, or removed.

    Removed: the base condition the message names, and none after. Made
    always true: the guard of the base marker `evidence._mark_weakened_guards`
    compared, under its old name for a skip moved into or out of a helper
    (#272), and the head marker's. A path gained by an unguarded
    `collect_ignore` (row 81) has no guard on either side.
    """
    if was is not None:
        return was, None
    before_by_name = {m.name: m for m in unit.before.markers}
    moved_from = {after: before for before, after in unit.delta.markers_moved}
    old = before_by_name.get(name) or before_by_name.get(moved_from.get(name, ""))
    return (old.guard if old is not None else None), (marker.guard if marker is not None else None)


def _row_texts(rows: Counter) -> list[dict]:
    """Rows as `{"names", "cells"}`, the cells in `identity_text`'s form, sorted by their encoding."""
    out = [{"names": list(names), "cells": [identity_text(cell) for cell in cells]}
           for (names, cells) in rows.elements()]
    return sorted(out, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True))


def _rows_gone(before, after) -> tuple[list[dict], list[dict]]:
    """(rows deleted, rows newly disabled) of a parametrized unit, each a sorted list.

    A row is its table's argnames and its cell texts, read through
    `param_tables` as `diffalign._rows_lost` reads them, the JS/TS tables of
    #428 included. Of the rows that ran before, one still written but marked
    off is newly disabled; one no longer written at all is deleted. An
    edited row's old text is among the deleted ones, since the rows alone
    cannot tell an edit from a deletion. A side whose tables cannot be read
    gives no rows: when it is the before side the key binds the counts alone,
    and when it is the after side every row that ran before reads as deleted.
    """
    def rows(side, disabled: bool) -> Counter:
        return Counter(
            (table.names, row)
            for table in param_tables(side)
            for row, flag in zip(table.rows, table.disabled)
            if flag == disabled
        )

    gone = rows(before, False) - rows(after, False)
    newly_disabled = gone & rows(after, True)
    return _row_texts(gone - newly_disabled), _row_texts(newly_disabled)


def finding_marker(finding: Finding, unit) -> str | None:
    """The disabling marker a TEST_DISABLED finding reports, or None for one that reports none.

    A marker-added finding is keyed by its marker (`_marker_added_key`). The
    others report no marker of their own: a unit gone, rows removed, a guard
    weakened or removed. D6 judges the marker a finding reports, not the unit
    it sits on (#208), so this is the one place that reads the name back: it
    rebuilds the key of each marker the unit added and returns the name whose
    key is the finding's.
    """
    if finding.rule != "TEST_DISABLED" or finding.shape not in (SHAPE_MARKER_ADDED, SHAPE_COLLECTION_CONTROL):
        return None
    if unit is None or unit.delta is None or unit.after is None:
        return None
    marker_by_name = {m.name: m for m in unit.after.markers}
    for name in unit.delta.markers_added:
        key = _marker_added_key(finding.path, unit.qualname, name, marker_by_name.get(name), finding.shape)
        if key == finding.fingerprint:
            return name
    return None


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
            continue
        for unit in file.units:
            if unit.before is not None and unit.after is None:
                # whole unit disappeared. Its legacy pre-image is what its
                # identity has always been: the assertions reached through a
                # helper method stay out of it (306 Sub-Q10). The key also
                # binds the complete texts of those same own assertions, a
                # JS/TS assertion with its expected value (#512).
                own = [a for a in unit.before.assertions if a.via is None]
                text = "\n".join(a.text for a in own) or unit.qualname
                identity = "\n".join(fingerprint_text(file.path, a) for a in own) or unit.qualname
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=f"{unit.qualname}: test unit disappeared",
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=text, span=unit.before.span),
                        after=None,
                        fingerprint=_key(
                            file.path, unit.qualname, identity, SHAPE_UNIT_REMOVED,
                            context={"assertions": [identity_text(a.text) for a in own]},
                        ),
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
                            fingerprint=_marker_added_key(file.path, unit.qualname, name, m, shape),
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
                elif is_helper_skip(name):
                    where, which = " in a helper this test calls", f" ({name})"
                elif is_rebound(name):
                    where, which = " of a later binding of this test's name", f" ({name})"
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
                shape = SHAPE_INERT_MARK if inert else SHAPE_GUARD_WEAKENED
                # The guard before and after, null when removed: with them in
                # the key, a guard removed and one made always true are two
                # keys (#512 Q2; THREATMODEL 54).
                guard_before, guard_after = _guards(name, unit, was, m)
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=message,
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=m.text, span=m.span) if m else None,
                        fingerprint=_key(
                            file.path, unit.qualname, f"guard:{name}", shape,
                            before=guard_before, after=guard_after,
                        ),
                        shape=shape,
                    )
                )
            if unit.delta.param_cases_removed:
                n = unit.delta.param_cases_removed
                disabled = unit.delta.param_cases_disabled
                before_n = unit.before.param_cases if unit.before else None
                after_n = unit.after.param_cases
                live_after = after_n if after_n is not None else 1
                shown_after = after_n
                if before_n is None:
                    # A plain JS/TS test whose pair is a `.each`/`.for` table
                    # of no rows, or of rows that cannot be counted (#428
                    # Q2a): the one item it was. Only that pairing reaches
                    # here without a count on the before side.
                    before_n = 1
                    if getattr(unit.after, "param_rows_unknown", False):
                        live_after = shown_after = "unknown"
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
                # Which rows went and how, and the live counts the message
                # gives, so approving one row's deletion covers no other row
                # (#512 Q2). A JS/TS table's rows are read the same way.
                deleted_rows, disabled_rows = _rows_gone(unit.before, unit.after)
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=message,
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=f"parametrize cases: {shown_after}", span=unit.after.span),
                        fingerprint=_key(
                            file.path, unit.qualname, "parametrize", SHAPE_PARAM_CASES_REMOVED,
                            context={
                                "deleted": deleted_rows,
                                "disabled": disabled_rows,
                                "live_before": before_n,
                                "live_after": live_after,
                            },
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
                    # File level: keyed under `<file>`, as the legacy key was,
                    # and bound to the focus call's text (#512 Q2).
                    fingerprint=_key(file.path, "<file>", focus.name, SHAPE_MARKER_ADDED, after=focus.text),
                    shape=SHAPE_MARKER_ADDED,
                )
            )
    return findings
