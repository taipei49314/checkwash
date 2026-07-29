"""TEST_DISABLED: skip/xfail marker added, or a whole test unit disappeared."""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR


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
                    )
                )
                continue
            if unit.delta is None or unit.after is None:
                continue
            if unit.delta.markers_added:
                marker_by_name = {m.name: m for m in unit.after.markers}
                for name in unit.delta.markers_added:
                    m = marker_by_name.get(name)
                    what = (
                        "suite-level collection control added"
                        if name.startswith("conftest.")
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
                    )
                )
    return findings
