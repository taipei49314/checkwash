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
from checkwash.ir.model import IR


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.before is not None and unit.after is None:
                # whole unit disappeared
                text = "\n".join(a.text for a in unit.before.assertions) or unit.qualname
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=f"{unit.qualname}: test unit disappeared",
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=text, span=unit.before.span),
                        after=None,
                        fingerprint=make_fingerprint("TEST_DISABLED", file.path, unit.qualname, text),
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
                    collection = name.startswith("conftest.")
                    what = (
                        "suite-level collection control added"
                        if collection
                        else "disabling marker added"
                    )
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
                                if collection
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
                before_n = unit.before.param_cases if unit.before else None
                after_n = unit.after.param_cases
                findings.append(
                    Finding(
                        rule="TEST_DISABLED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: {n} parametrized case(s) deleted "
                            f"({before_n} -> {after_n if after_n is not None else 1})"
                        ),
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
    return findings
