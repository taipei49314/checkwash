""".gwcase format: one self-contained before/after fixture per file.

Sections:

    === meta ===
    rule: ASSERT_WEAKENED
    === task ===            (optional TASK.md content)
    === before: tests/test_x.py ===
    ...
    === after: tests/test_x.py ===
    ...
    === expect ===
    [{"rule": "...", "severity": "high"}]

A path appearing only in `after` is an added file; only in `before`, deleted.
Expectations are matched strictly: same count, and every expected finding
must match a distinct actual finding on every key it specifies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from greenwash.engine import FileChange

_SECTION_RE = re.compile(r"^=== (meta|task|expect|before: (?P<bpath>.+?)|after: (?P<apath>.+?)) ===$")


@dataclass
class Case:
    meta: dict[str, str] = field(default_factory=dict)
    task: str | None = None
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)
    expect: list[dict] = field(default_factory=list)


def parse_case(text: str) -> Case:
    case = Case()
    current: tuple[str, str | None] | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is None:
            return
        kind, path = current
        content = "\n".join(buf)
        if kind == "meta":
            for line in content.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    case.meta[k.strip()] = v.strip()
        elif kind == "task":
            case.task = content
        elif kind == "expect":
            case.expect = json.loads(content) if content.strip() else []
        elif kind == "before":
            case.before[path or ""] = content
        elif kind == "after":
            case.after[path or ""] = content

    for line in text.replace("\r\n", "\n").split("\n"):
        m = _SECTION_RE.match(line.strip()) if line.startswith("===") else None
        if m:
            flush()
            buf = []
            if m.group("bpath"):
                current = ("before", m.group("bpath"))
            elif m.group("apath"):
                current = ("after", m.group("apath"))
            else:
                current = (m.group(1), None)
        elif current is not None:
            buf.append(line)
    flush()
    return case


def case_to_changes(case: Case) -> list[FileChange]:
    changes: list[FileChange] = []
    for path in sorted(set(case.before) | set(case.after)):
        b = case.before.get(path)
        a = case.after.get(path)
        if b is None:
            status = "added"
        elif a is None:
            status = "deleted"
        else:
            status = "modified"
        changes.append(
            FileChange(
                path=path,
                status=status,
                before=b.encode("utf-8") if b is not None else None,
                after=a.encode("utf-8") if a is not None else None,
            )
        )
    return changes


def match_expectations(expect: list[dict], findings: list) -> str | None:
    """None if the strict match holds, else a human-readable mismatch reason."""
    actual = [
        {
            "rule": f.rule,
            "severity": f.severity,
            "escalators": list(f.escalators),
            "deescalators": list(f.deescalators),
            "path": f.path,
            "unit": f.unit,
        }
        for f in findings
    ]
    if len(expect) != len(actual):
        return f"expected {len(expect)} finding(s), got {len(actual)}: {json.dumps(actual)}"
    remaining = list(actual)
    for exp in expect:
        matched = None
        for i, act in enumerate(remaining):
            ok = True
            for key, want in exp.items():
                have = act.get(key)
                if isinstance(want, list):
                    if not set(want).issubset(set(have or [])):
                        ok = False
                        break
                elif have != want:
                    ok = False
                    break
            if ok:
                matched = i
                break
        if matched is None:
            return f"no actual finding matches expectation {json.dumps(exp)}; actuals: {json.dumps(remaining)}"
        remaining.pop(matched)
    return None
